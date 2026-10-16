"""Injectable clock. Domain code never calls time.monotonic() directly.

TTLs are measured on a monotonic clock, not wall time: if an operator moves
the system clock back an hour, entries must not suddenly live an hour longer.
Tests use FakeClock and move time forward by hand.
"""
import threading
import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> float:
        """Seconds on a clock that never goes backwards."""


class SystemClock(Clock):
    def now(self) -> float:
        return time.monotonic()


class FakeClock(Clock):
    """A clock that only moves when a test says so. Safe to share across threads."""

    def __init__(self, start: float = 0.0) -> None:
        self._lock = threading.Lock()  # guards _now
        self._now = start

    def now(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("a monotonic clock cannot go backwards")
        with self._lock:
            self._now += seconds
