"""The TrafficManagementCenter: plans out, heartbeats out, telemetry in.

The centre holds *desired* state (which plan each controller should run)
and reconciles it on every heartbeat round. A plan set while a link is down
is not lost: it is delivered on the first round after the link returns.

Emergency preemption runs along a route. Each intersection on the route is
preempted preempt_lead_time seconds before the vehicle's ETA and released
preempt_release_after seconds after it. A leg that cannot be preempted yet
(link down, conflicting preemption, fault flash) is retried every second.

Lock order: self._lock -> controller lock -> uplink lock -> self._status_lock.
on_event() takes only _status_lock and never calls out, so a controller
publishing telemetry can never deadlock against the centre.
"""
import logging
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum

from .clock import Clock
from .comms import CommsNetwork
from .config import TmcConfig
from .controller import IntersectionController
from .errors import (
    CommunicationLostError,
    EmergencyDispatchError,
    InvalidConfigError,
    TrafficError,
    UnknownIntersectionError,
)
from .events import ModeChanged, PhaseChanged, TelemetryEvent, TelemetryListener
from .models import Axis, ControlMode, Phase
from .network import RoadNetwork
from .timing import TimingStrategy

log = logging.getLogger(__name__)


class LegState(Enum):
    PENDING = "pending"
    HELD = "held"
    RELEASED = "released"
    MISSED = "missed"  # the vehicle passed before we could ever preempt


@dataclass
class _Leg:
    intersection_id: str
    approach: Axis
    eta: int
    state: LegState = LegState.PENDING


@dataclass(frozen=True)
class IntersectionStatus:
    phase: Phase | None
    mode: ControlMode | None
    last_heard: int | None


class TrafficManagementCenter(TelemetryListener):
    def __init__(
        self,
        network: RoadNetwork,
        comms: CommsNetwork,
        clock: Clock,
        config: TmcConfig = TmcConfig(),
    ) -> None:
        self._network = network
        self._comms = comms
        self._clock = clock
        self._config = config
        self._lock = threading.RLock()  # guards controllers, plans, runs, round time
        self._controllers: dict[str, IntersectionController] = {}
        self._desired: dict[str, TimingStrategy] = {}
        self._undelivered: set[str] = set()
        self._runs: dict[str, list[_Leg]] = {}
        self._last_round: int | None = None
        self._status_lock = threading.Lock()  # leaf lock: guards _status only
        self._status: dict[str, IntersectionStatus] = {}

    # ------------------------------------------------------------ wiring
    def register(self, controller: IntersectionController) -> None:
        if self._config.heartbeat_interval >= controller.heartbeat_timeout:
            raise InvalidConfigError(
                f"heartbeat_interval {self._config.heartbeat_interval}s must be shorter "
                f"than {controller.intersection_id}'s timeout {controller.heartbeat_timeout}s"
            )
        with self._lock:
            self._controllers[controller.intersection_id] = controller
        with self._status_lock:
            self._status[controller.intersection_id] = IntersectionStatus(None, None, None)

    # ------------------------------------------------------------- plans
    def set_plan(self, intersection_id: str, plan: TimingStrategy) -> bool:
        """Record the desired plan and try to deliver it now.
        Returns True if delivered, False if it will be retried."""
        with self._lock:
            self._controller(intersection_id)
            self._desired[intersection_id] = plan
            self._undelivered.add(intersection_id)
            return self._try_deliver(intersection_id)

    def set_plans(self, plans: Mapping[str, TimingStrategy]) -> None:
        for intersection_id, plan in plans.items():
            self.set_plan(intersection_id, plan)

    # ---------------------------------------------------------- incidents
    def report_incident(self, link_id: str, lanes_closed: int) -> None:
        """Close lanes on a link. Routing avoids fully closed links at once;
        the downstream controller learns its reduced capacity."""
        capacity = self._network.set_lanes_closed(link_id, lanes_closed)
        link = self._network.link(link_id)
        log.warning("incident on %s: %d lane(s) closed, capacity %s", link_id, lanes_closed, capacity)
        if capacity == 0:
            return  # nothing arrives on this approach any more
        with self._lock:
            controller = self._controller(link.to_id)
            try:
                self._send(link.to_id, lambda: controller.set_capacity(link.approach, capacity))
            except CommunicationLostError:
                log.warning("could not tell %s about the incident; link down", link.to_id)

    # ---------------------------------------------------------- emergency
    def dispatch_emergency(
        self, vehicle_id: str, origin: str, destination: str, speed_mps: float
    ) -> list[str]:
        """Plan a preemption run along the shortest open route.
        Returns the intersection ids the vehicle will pass, in order."""
        if speed_mps <= 0:
            raise EmergencyDispatchError("speed must be positive")
        route = self._network.shortest_route(origin, destination)
        now = self._clock.now()
        legs: list[_Leg] = []
        travelled = 0
        for link in route:
            travelled += link.length_m
            eta = now + math.ceil(travelled / speed_mps)
            legs.append(_Leg(link.to_id, link.approach, eta))
        with self._lock:
            if vehicle_id in self._runs:
                raise EmergencyDispatchError(f"{vehicle_id} is already dispatched")
            for leg in legs:
                self._controller(leg.intersection_id)
            self._runs[vehicle_id] = legs
        log.info("dispatched %s via %s", vehicle_id, [leg.intersection_id for leg in legs])
        return [leg.intersection_id for leg in legs]

    def emergency_legs(self, vehicle_id: str) -> list[tuple[str, LegState]]:
        with self._lock:
            legs = self._runs.get(vehicle_id)
            if legs is None:
                raise EmergencyDispatchError(f"unknown run {vehicle_id}")
            return [(leg.intersection_id, leg.state) for leg in legs]

    # --------------------------------------------------------- time passing
    def step(self) -> None:
        """Call once per simulated second, after the controllers have stepped."""
        now = self._clock.now()
        with self._lock:
            due = self._last_round is None or now - self._last_round >= self._config.heartbeat_interval
            if due:
                self._last_round = now
                self._heartbeat_round()
            self._advance_runs(now)

    # ------------------------------------------------------------ telemetry
    def on_event(self, event: TelemetryEvent) -> None:
        with self._status_lock:
            old = self._status.get(event.intersection_id, IntersectionStatus(None, None, None))
            phase = event.phase if isinstance(event, PhaseChanged) else old.phase
            mode = event.mode if isinstance(event, ModeChanged) else old.mode
            self._status[event.intersection_id] = IntersectionStatus(phase, mode, event.at)

    def status(self, intersection_id: str) -> IntersectionStatus:
        with self._status_lock:
            try:
                return self._status[intersection_id]
            except KeyError:
                raise UnknownIntersectionError(intersection_id) from None

    # ------------------------------------------------------------ internals
    def _controller(self, intersection_id: str) -> IntersectionController:
        try:
            return self._controllers[intersection_id]
        except KeyError:
            raise UnknownIntersectionError(intersection_id) from None

    def _send(self, intersection_id: str, command: Callable[[], object]) -> object:
        if not self._comms.is_up(intersection_id):
            raise CommunicationLostError(intersection_id)
        return command()

    def _try_deliver(self, intersection_id: str) -> bool:
        controller = self._controllers[intersection_id]
        plan = self._desired[intersection_id]
        try:
            self._send(intersection_id, lambda: controller.apply_plan(plan))
        except CommunicationLostError:
            return False
        self._undelivered.discard(intersection_id)
        return True

    def _heartbeat_round(self) -> None:
        for intersection_id in sorted(self._controllers):
            controller = self._controllers[intersection_id]
            try:
                self._send(intersection_id, controller.heartbeat)
            except CommunicationLostError:
                continue
            if intersection_id in self._undelivered:
                self._try_deliver(intersection_id)

    def _advance_runs(self, now: int) -> None:
        lead = self._config.preempt_lead_time
        after = self._config.preempt_release_after
        for vehicle_id, legs in self._runs.items():
            for leg in legs:
                controller = self._controllers[leg.intersection_id]
                if leg.state is LegState.PENDING and now >= leg.eta + after:
                    leg.state = LegState.MISSED
                    log.error("%s passed %s without preemption", vehicle_id, leg.intersection_id)
                elif leg.state is LegState.PENDING and now >= leg.eta - lead:
                    try:
                        self._send(leg.intersection_id,
                                   lambda: controller.preempt(leg.approach, vehicle_id))
                        leg.state = LegState.HELD
                    except TrafficError as exc:  # conflict, link down, fault flash
                        log.info("%s at %s waiting: %s", vehicle_id, leg.intersection_id, exc)
                elif leg.state is LegState.HELD and now >= leg.eta + after:
                    try:
                        self._send(leg.intersection_id, lambda: controller.release(vehicle_id))
                        leg.state = LegState.RELEASED
                    except CommunicationLostError:
                        pass  # retried next second; the controller's own hold limit backs us up
