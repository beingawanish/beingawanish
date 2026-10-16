"""Injectable clock. Opening hours, offer timeouts and ETAs all read time,
so domain code asks a Clock and tests freeze it with FixedClock.
Every datetime is timezone-aware, in UTC."""
import threading
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        ...


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    """A clock that moves only when told to. The lock guards _now, because
    the concurrency tests read it from several threads at once."""

    def __init__(self, now: datetime):
        self._lock = threading.Lock()
        self._now = now

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, **delta: float) -> None:
        """advance(seconds=31), advance(minutes=5): any timedelta keyword."""
        with self._lock:
            self._now += timedelta(**delta)
