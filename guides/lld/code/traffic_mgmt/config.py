"""Every tunable number in the system, in frozen, validated dataclasses.

No other module contains a literal duration, rate or limit. A traffic
engineer can audit the whole timing policy by reading this one file.
"""
from dataclasses import dataclass, field

from .errors import InvalidConfigError

SECONDS_PER_DAY = 86_400  # a unit conversion, not a tunable


def _require_positive_ints(obj: object, *names: str) -> None:
    for name in names:
        value = getattr(obj, name)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidConfigError(
                f"{type(obj).__name__}.{name} must be a positive int, got {value!r}"
            )


@dataclass(frozen=True)
class SafetyTimings:
    """Floors and clearances that no timing plan is allowed to undercut."""

    min_green: int = 7
    yellow: int = 3
    all_red: int = 2

    def __post_init__(self) -> None:
        _require_positive_ints(self, "min_green", "yellow", "all_red")

    @property
    def clearance(self) -> int:
        """Yellow plus all-red: the cost of handing the junction over once."""
        return self.yellow + self.all_red


@dataclass(frozen=True)
class AdaptiveTuning:
    """How the adaptive plan turns a queue count into green seconds."""

    base_green: int = 10
    seconds_per_vehicle: int = 2
    max_green: int = 60

    def __post_init__(self) -> None:
        _require_positive_ints(self, "base_green", "seconds_per_vehicle", "max_green")
        if self.base_green > self.max_green:
            raise InvalidConfigError("base_green cannot exceed max_green")


@dataclass(frozen=True)
class DischargeConfig:
    """Saturation flow: one vehicle crosses the stop line every N green seconds."""

    seconds_per_departure: int = 2

    def __post_init__(self) -> None:
        _require_positive_ints(self, "seconds_per_departure")


@dataclass(frozen=True)
class FailsafeConfig:
    """What a controller does when the centre goes quiet or hardware fails."""

    heartbeat_timeout: int = 15
    fallback_ns_green: int = 20
    fallback_ew_green: int = 20
    max_preempt_hold: int = 120
    telemetry_buffer: int = 100

    def __post_init__(self) -> None:
        _require_positive_ints(
            self,
            "heartbeat_timeout",
            "fallback_ns_green",
            "fallback_ew_green",
            "max_preempt_hold",
            "telemetry_buffer",
        )


@dataclass(frozen=True)
class ControllerConfig:
    """Everything one intersection controller needs to know."""

    safety: SafetyTimings = field(default_factory=SafetyTimings)
    discharge: DischargeConfig = field(default_factory=DischargeConfig)
    failsafe: FailsafeConfig = field(default_factory=FailsafeConfig)

    def __post_init__(self) -> None:
        for name in ("fallback_ns_green", "fallback_ew_green"):
            if getattr(self.failsafe, name) < self.safety.min_green:
                raise InvalidConfigError(f"failsafe.{name} is below safety.min_green")


@dataclass(frozen=True)
class TmcConfig:
    """The centre's own timing: heartbeats and emergency preemption windows."""

    heartbeat_interval: int = 5
    preempt_lead_time: int = 20
    preempt_release_after: int = 5

    def __post_init__(self) -> None:
        _require_positive_ints(
            self, "heartbeat_interval", "preempt_lead_time", "preempt_release_after"
        )
