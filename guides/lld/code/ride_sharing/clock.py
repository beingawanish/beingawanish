"""The injectable clock. Offer timeouts, cancellation windows and trip
durations all read time from here, never from datetime.now() directly."""
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta

from .errors import InvalidInputError


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware."""


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock(Clock):
    """A clock that moves only when a test tells it to.

    Thread-safe: the lock guards _now, because a concurrency test may read
    the time on many threads while the main thread advances it.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise InvalidInputError("start must be timezone-aware")
        self._now = start
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> datetime:
        if seconds < 0:
            raise InvalidInputError("time only moves forward")
        with self._lock:
            self._now += timedelta(seconds=seconds)
            return self._now
