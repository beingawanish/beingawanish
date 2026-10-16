"""Injectable monotonic clock. Durations and idempotency expiry read it;
tests replace it with FakeClock and move time by hand."""
import threading
import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> float:
        """Seconds on a monotonic scale. Only differences are meaningful."""


class SystemClock(Clock):
    def now(self) -> float:
        return time.monotonic()


class FakeClock(Clock):
    """Test clock. Thread-safe, because tool threads read it concurrently."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._lock = threading.Lock()  # guards _now

    def now(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds
