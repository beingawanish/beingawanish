"""Injectable time and ids, so tests and demos are deterministic."""

import itertools
import threading
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    """Test clock: returns a set time until advanced. Not thread-safe; tests only."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = at


class IdGenerator(ABC):
    @abstractmethod
    def next_id(self, prefix: str) -> str:
        """A fresh id such as 'exp-3'. Never repeats within one generator."""


class UuidIds(IdGenerator):
    def next_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid.uuid4().hex[:12]}"


class SequentialIds(IdGenerator):
    """Readable ids, one counter per prefix. The lock guards the counter map."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, itertools.count[int]] = {}

    def next_id(self, prefix: str) -> str:
        with self._lock:
            counter = self._counters.setdefault(prefix, itertools.count(1))
            return f"{prefix}-{next(counter)}"
