"""Vehicle-count sensors and the queues they measure.

ApproachQueues is the simulated road surface at one intersection: vehicles
arrive on an approach, wait, and leave during that approach's green at the
saturation-flow rate. count() is what the loop detector reports.

Fractions keep the discharge arithmetic exact, so a lane closure that
halves capacity halves departures with no float dust.
"""
import threading
from fractions import Fraction

from .config import DischargeConfig
from .models import Axis

FULL_CAPACITY = Fraction(1)


class ApproachQueues:
    """Queue length and capacity per axis at one intersection. Thread-safe."""

    def __init__(self, discharge: DischargeConfig) -> None:
        self._discharge = discharge
        self._lock = threading.Lock()  # guards the three dicts below
        self._queue: dict[Axis, int] = {axis: 0 for axis in Axis}
        self._credit: dict[Axis, Fraction] = {axis: Fraction(0) for axis in Axis}
        self._capacity: dict[Axis, Fraction] = {axis: FULL_CAPACITY for axis in Axis}

    def arrive(self, axis: Axis, vehicles: int) -> None:
        if isinstance(vehicles, bool) or not isinstance(vehicles, int) or vehicles < 0:
            raise ValueError(f"vehicles must be a non-negative int, got {vehicles!r}")
        with self._lock:
            self._queue[axis] += vehicles

    def discharge(self, axis: Axis, green_seconds: int = 1) -> int:
        """Let vehicles leave for green_seconds of green. Returns how many left."""
        with self._lock:
            rate = self._capacity[axis] / self._discharge.seconds_per_departure
            self._credit[axis] += rate * green_seconds
            leaving = min(self._queue[axis], int(self._credit[axis]))
            self._queue[axis] -= leaving
            self._credit[axis] -= leaving
            if self._queue[axis] == 0:
                self._credit[axis] = Fraction(0)  # an empty road banks no green
            return leaving

    def count(self, axis: Axis) -> int:
        """The detector reading: vehicles currently queued on this approach."""
        with self._lock:
            return self._queue[axis]

    def set_capacity(self, axis: Axis, capacity: Fraction) -> None:
        """Share of normal saturation flow still available (lane closures)."""
        if not 0 < capacity <= 1:
            raise ValueError(f"capacity must be in (0, 1], got {capacity}")
        with self._lock:
            self._capacity[axis] = Fraction(capacity)

    def capacity(self, axis: Axis) -> Fraction:
        with self._lock:
            return self._capacity[axis]
