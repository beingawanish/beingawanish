"""The vocabulary: axes, phases, control modes, and the green split."""
from dataclasses import dataclass
from enum import Enum

from .errors import InvalidPlanError


class Axis(Enum):
    """The two movements at a two-road intersection."""

    NS = "ns"
    EW = "ew"

    @property
    def other(self) -> "Axis":
        return Axis.EW if self is Axis.NS else Axis.NS


class Phase(Enum):
    NS_GREEN = "ns_green"
    NS_YELLOW = "ns_yellow"
    ALL_RED = "all_red"
    EW_GREEN = "ew_green"
    EW_YELLOW = "ew_yellow"
    PREEMPT_NS = "preempt_ns"  # held green for an emergency vehicle
    PREEMPT_EW = "preempt_ew"
    FLASHING_RED = "flashing_red"  # fault flash: every approach is an all-way stop


GREEN: dict[Axis, Phase] = {Axis.NS: Phase.NS_GREEN, Axis.EW: Phase.EW_GREEN}
YELLOW: dict[Axis, Phase] = {Axis.NS: Phase.NS_YELLOW, Axis.EW: Phase.EW_YELLOW}
PREEMPT: dict[Axis, Phase] = {Axis.NS: Phase.PREEMPT_NS, Axis.EW: Phase.PREEMPT_EW}


def moving_axis(phase: Phase) -> Axis | None:
    """The axis whose traffic may enter the junction in this phase, if any."""
    for axis in Axis:
        if phase in (GREEN[axis], PREEMPT[axis]):
            return axis
    return None


class ControlMode(Enum):
    CENTRAL = "central"  # running the plan the centre pushed
    LOCAL_FALLBACK = "local_fallback"  # centre silent: safe local fixed-time plan
    FLASHING = "flashing"  # hardware fault: flash until a technician resets


@dataclass(frozen=True)
class GreenSplit:
    """Green seconds for each axis in one cycle, and the plan that chose them."""

    ns: int
    ew: int
    plan: str

    def __post_init__(self) -> None:
        for name in ("ns", "ew"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise InvalidPlanError(f"green for {name} must be a positive int, got {value!r}")

    def green_for(self, axis: Axis) -> int:
        return self.ns if axis is Axis.NS else self.ew
