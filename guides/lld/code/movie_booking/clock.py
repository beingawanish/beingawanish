"""Injectable clock. Hold expiry is pure time arithmetic, so tests must own time.

Domain code never calls datetime.now() directly. FixedClock lets a test jump
ten minutes forward in one line instead of sleeping for ten minutes.
"""
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, always timezone-aware."""


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock(Clock):
    """Test clock. Thread-safe, because the concurrency tests read it from many threads."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime")
        self._now = start
        self._lock = threading.Lock()  # guards _now

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._now += delta
