"""The injectable clock. Rate limiting is arithmetic on time, so time is a seam.

Times are plain float seconds from a monotonic source. Wall-clock time can jump
backwards (NTP, daylight saving); a limiter fed by it would refill buckets twice.
"""
import threading
import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> float:
        """Seconds since an arbitrary, fixed origin. Never decreases."""


class MonotonicClock(Clock):
    """Production clock: time.monotonic()."""

    def now(self) -> float:
        return time.monotonic()


class ManualClock(Clock):
    """Test clock that only moves when told to. Safe to share across threads."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._lock = threading.Lock()  # guards _now

    def now(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError(f"a monotonic clock cannot go back ({seconds})")
        with self._lock:
            self._now += seconds
