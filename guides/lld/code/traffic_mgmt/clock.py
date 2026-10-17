"""Injectable time. Domain code asks a Clock; it never reads the wall.

Time is a whole number of seconds. ManualClock starts at any second you
like (7 * 3600 is 07:00 on day zero) and moves only when the simulation
advances it, so every test and every demo run is exactly repeatable.
"""
import threading
import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> int:
        """Current time in whole seconds."""


class SystemClock(Clock):
    """Wall-clock seconds since the Unix epoch (UTC) for a real deployment."""

    def now(self) -> int:
        return int(time.time())


class ManualClock(Clock):
    """A clock that moves only when told to. Safe to share between threads."""

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ValueError("start must be >= 0")
        self._now = start
        self._lock = threading.Lock()  # guards _now

    def now(self) -> int:
        with self._lock:
            return self._now

    def advance(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("time only moves forward")
        with self._lock:
            self._now += seconds
