"""One intersection's signal controller: a state machine with three masters.

1. Its timing plan (Strategy) sets the green split, once per cycle.
2. The centre sends heartbeats, plans and preemption calls. Silence for
   longer than heartbeat_timeout drops the controller to its local
   fixed-time fallback plan. The next heartbeat brings it back.
3. Safety outranks both. Every phase change goes through TRANSITIONS,
   yellow and all-red are never skipped, and a hardware fault drops
   straight into FLASHING_RED, the one move that needs no permission.

The controller never reads a wall clock. The simulation advances the
shared Clock by one second and then calls step() exactly once.
"""
import logging
import threading
from fractions import Fraction

from .clock import Clock
from .config import ControllerConfig
from .errors import IllegalTransitionError, PreemptionConflictError, SignalFaultError
from .events import CycleStarted, ModeChanged, PhaseChanged, TelemetrySink
from .models import GREEN, PREEMPT, YELLOW, Axis, ControlMode, GreenSplit, Phase
from .sensors import ApproachQueues
from .timing import CycleContext, FixedTimePlan, TimingStrategy

log = logging.getLogger(__name__)

TRANSITIONS: dict[Phase, frozenset[Phase]] = {
    Phase.ALL_RED: frozenset(
        {Phase.NS_GREEN, Phase.EW_GREEN, Phase.PREEMPT_NS, Phase.PREEMPT_EW}
    ),
    Phase.NS_GREEN: frozenset({Phase.NS_YELLOW, Phase.PREEMPT_NS}),
    Phase.NS_YELLOW: frozenset({Phase.ALL_RED}),
    Phase.EW_GREEN: frozenset({Phase.EW_YELLOW, Phase.PREEMPT_EW}),
    Phase.EW_YELLOW: frozenset({Phase.ALL_RED}),
    Phase.PREEMPT_NS: frozenset({Phase.NS_YELLOW}),
    Phase.PREEMPT_EW: frozenset({Phase.EW_YELLOW}),
    Phase.FLASHING_RED: frozenset({Phase.ALL_RED}),
}
# Not in the table on purpose: any phase -> FLASHING_RED. A conflict monitor
# that detects a fault does not ask the state machine for permission.

_HELD = frozenset({Phase.PREEMPT_NS, Phase.PREEMPT_EW, Phase.FLASHING_RED})


class IntersectionController:
    """Thread-safe: every public method takes self._lock (an RLock)."""

    def __init__(
        self,
        intersection_id: str,
        clock: Clock,
        queues: ApproachQueues,
        telemetry: TelemetrySink,
        config: ControllerConfig = ControllerConfig(),
        fallback: TimingStrategy | None = None,
    ) -> None:
        if not intersection_id:
            raise ValueError("intersection_id must be non-empty")
        self.intersection_id = intersection_id
        self._clock = clock
        self._queues = queues
        self._telemetry = telemetry
        self._safety = config.safety
        self._failsafe = config.failsafe
        self._fallback = fallback or FixedTimePlan(
            config.failsafe.fallback_ns_green, config.failsafe.fallback_ew_green, "local-fixed"
        )
        # self._lock guards every attribute below. Lock order across the
        # system: TMC lock -> controller lock -> uplink lock -> listener locks.
        self._lock = threading.RLock()
        self._phase = Phase.ALL_RED  # boot into clearance, never into a green
        self._elapsed = 0
        self._duration = self._safety.all_red
        self._next_axis = Axis.NS
        self._split: GreenSplit | None = None
        self._central_plan: TimingStrategy | None = None
        self._mode = ControlMode.LOCAL_FALLBACK  # until the centre says hello
        self._last_heartbeat: int | None = None
        self._preempt_axis: Axis | None = None
        self._preempt_holders: set[str] = set()

    # ------------------------------------------------------------ queries
    @property
    def phase(self) -> Phase:
        with self._lock:
            return self._phase

    @property
    def mode(self) -> ControlMode:
        with self._lock:
            return self._mode

    @property
    def preempted_by(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._preempt_holders)

    @property
    def heartbeat_timeout(self) -> int:
        return self._failsafe.heartbeat_timeout

    # ------------------------------------------------------- time passing
    def step(self) -> None:
        """Account for the one second that just elapsed on the shared clock."""
        with self._lock:
            if self._phase is Phase.FLASHING_RED:
                return
            self._check_heartbeat()
            for axis in Axis:
                if self._phase in (GREEN[axis], PREEMPT[axis]):
                    self._queues.discharge(axis)
            self._elapsed += 1
            if self._phase in _HELD:
                if self._elapsed >= self._failsafe.max_preempt_hold:
                    log.warning("%s: preemption held %ss, auto-releasing",
                                self.intersection_id, self._elapsed)
                    self._end_preemption()
                return
            if self._elapsed >= self._duration:
                self._advance()

    # ----------------------------------------------------- centre commands
    def heartbeat(self) -> None:
        with self._lock:
            self._last_heartbeat = self._clock.now()
            if self._mode is ControlMode.LOCAL_FALLBACK:
                self._set_mode(ControlMode.CENTRAL, "heartbeat received")

    def apply_plan(self, plan: TimingStrategy) -> None:
        """Store the centre's plan. It takes effect at the next cycle start."""
        with self._lock:
            self._central_plan = plan
            log.info("%s: plan %r queued for next cycle", self.intersection_id, plan.name)

    def preempt(self, axis: Axis, vehicle_id: str) -> None:
        """Give `axis` a held green for an emergency vehicle, safely."""
        with self._lock:
            if self._phase is Phase.FLASHING_RED:
                raise SignalFaultError(f"{self.intersection_id} is in fault flash")
            if self._preempt_axis not in (None, axis):
                raise PreemptionConflictError(
                    f"{self.intersection_id} already preempted for {self._preempt_axis.name}"
                )
            self._preempt_holders.add(vehicle_id)
            self._preempt_axis = axis
            if self._phase is GREEN[axis]:
                self._enter(PREEMPT[axis])  # already green: just hold it
            elif self._phase is GREEN[axis.other]:
                self._enter(YELLOW[axis.other])  # cut the cross green, keep clearance
            # Yellow or all-red: let clearance finish; _advance routes to PREEMPT.

    def release(self, vehicle_id: str) -> bool:
        """Drop one vehicle's hold. Returns False if it held nothing here."""
        with self._lock:
            if vehicle_id not in self._preempt_holders:
                return False
            self._preempt_holders.discard(vehicle_id)
            if not self._preempt_holders:
                self._end_preemption()
            return True

    def set_capacity(self, axis: Axis, capacity: Fraction) -> None:
        """Record a lane closure so adaptive plans can stretch that green."""
        with self._lock:
            self._queues.set_capacity(axis, capacity)

    # ------------------------------------------------------ fault handling
    def report_fault(self, reason: str) -> None:
        """Conflict monitor tripped: flash immediately, drop everything else."""
        with self._lock:
            self._preempt_holders.clear()
            self._preempt_axis = None
            self._enter(Phase.FLASHING_RED, force=True)
            self._set_mode(ControlMode.FLASHING, reason)

    def reset_fault(self) -> None:
        """Technician reset: clearance first, then a fresh cycle."""
        with self._lock:
            if self._phase is not Phase.FLASHING_RED:
                raise IllegalTransitionError(f"{self.intersection_id} is not flashing")
            self._next_axis = Axis.NS
            self._split = None
            self._enter(Phase.ALL_RED)
            self._set_mode(
                ControlMode.CENTRAL if self._heartbeat_fresh() else ControlMode.LOCAL_FALLBACK,
                "fault reset",
            )

    # ------------------------------------------------------------ internals
    def _heartbeat_fresh(self) -> bool:
        if self._last_heartbeat is None:
            return False
        return self._clock.now() - self._last_heartbeat <= self._failsafe.heartbeat_timeout

    def _check_heartbeat(self) -> None:
        if self._mode is ControlMode.CENTRAL and not self._heartbeat_fresh():
            self._set_mode(ControlMode.LOCAL_FALLBACK, "heartbeat timeout")

    def _set_mode(self, mode: ControlMode, reason: str) -> None:
        if mode is self._mode:
            return
        self._mode = mode
        log.warning("%s: mode -> %s (%s)", self.intersection_id, mode.name, reason)
        self._telemetry.send(ModeChanged(self.intersection_id, self._clock.now(), mode, reason))

    def _end_preemption(self) -> None:
        axis, self._preempt_axis = self._preempt_axis, None
        self._preempt_holders.clear()
        if axis is not None and self._phase is PREEMPT[axis]:
            self._enter(YELLOW[axis])

    def _advance(self) -> None:
        phase = self._phase
        if phase in (Phase.NS_GREEN, Phase.EW_GREEN):
            axis = Axis.NS if phase is Phase.NS_GREEN else Axis.EW
            self._enter(YELLOW[axis])
        elif phase in (Phase.NS_YELLOW, Phase.EW_YELLOW):
            axis = Axis.NS if phase is Phase.NS_YELLOW else Axis.EW
            self._next_axis = axis.other
            self._enter(Phase.ALL_RED)
        elif phase is Phase.ALL_RED:
            if self._preempt_axis is not None:
                self._enter(PREEMPT[self._preempt_axis])
            else:
                if self._next_axis is Axis.NS or self._split is None:
                    self._split = self._plan_cycle()
                self._enter(GREEN[self._next_axis])

    def _active_plan(self) -> TimingStrategy:
        if self._mode is ControlMode.CENTRAL and self._central_plan is not None:
            return self._central_plan
        return self._fallback

    def _plan_cycle(self) -> GreenSplit:
        plan = self._active_plan()
        ctx = CycleContext(
            now=self._clock.now(),
            queue_ns=self._queues.count(Axis.NS),
            queue_ew=self._queues.count(Axis.EW),
            capacity_ns=self._queues.capacity(Axis.NS),
            capacity_ew=self._queues.capacity(Axis.EW),
        )
        raw = plan.split(ctx)
        floor = self._safety.min_green
        split = GreenSplit(max(raw.ns, floor), max(raw.ew, floor), raw.plan)
        if split != raw:
            log.warning("%s: plan %r undercut min_green; clamped", self.intersection_id, raw.plan)
        self._telemetry.send(
            CycleStarted(self.intersection_id, ctx.now, split, ctx.queue_ns, ctx.queue_ew)
        )
        return split

    def _duration_of(self, phase: Phase) -> int:
        if phase in (Phase.NS_YELLOW, Phase.EW_YELLOW):
            return self._safety.yellow
        if phase is Phase.ALL_RED:
            return self._safety.all_red
        if phase in (Phase.NS_GREEN, Phase.EW_GREEN) and self._split is not None:
            return self._split.green_for(Axis.NS if phase is Phase.NS_GREEN else Axis.EW)
        return 0  # held phases have no duration; step() never times them out

    def _enter(self, phase: Phase, *, force: bool = False) -> None:
        if not force and phase not in TRANSITIONS[self._phase]:
            raise IllegalTransitionError(f"{self._phase.name} -> {phase.name}")
        self._phase = phase
        self._elapsed = 0
        self._duration = self._duration_of(phase)
        log.debug("%s: %s", self.intersection_id, phase.name)
        self._telemetry.send(PhaseChanged(self.intersection_id, self._clock.now(), phase))
