"""Injectable clock. The gateway reads time and sleeps only through this seam,
so tests run backoff, cooldowns and rate windows instantly with FakeClock."""
import threading
import time
from abc import ABC, abstractmethod


class Clock(ABC):
    @abstractmethod
    def now(self) -> float:
        """Seconds on a monotonic scale."""

    @abstractmethod
    def sleep(self, seconds: float) -> None:
        ...


class SystemClock(Clock):
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FakeClock(Clock):
    """Sleeping advances time instead of blocking. The lock guards _now,
    because the concurrency tests call sleep() from many threads."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("time only moves forward")
        with self._lock:
            self._now += seconds
