"""The storage seam: where per-key state lives, and how it is updated atomically.

The whole contract is one method, update(): read a key's state, run the
algorithm's step on it, write the result back with an expiry, all as one atomic
unit. In memory that is a lock. In Redis it is a Lua script (see the chapter's
follow-ups); the limiter cannot tell the difference.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


class StateStore(ABC):
    @abstractmethod
    def update[R](self, key: str, now: float, ttl: float,
                  step: Callable[[Any | None], tuple[Any, R]]) -> R:
        """Atomically apply `step` to the key's state and return its result.

        `step` receives None when the key is missing or expired. Its new state is
        stored with an expiry of now + ttl. Raises StoreError if the store fails.
        """

    @abstractmethod
    def purge_expired(self, now: float) -> int:
        """Delete every key whose expiry has passed. Returns how many went."""

    @abstractmethod
    def __len__(self) -> int:
        """Number of keys currently held, expired or not."""


@dataclass(slots=True)
class _Entry:
    state: Any
    expires_at: float


class InMemoryStore(StateStore):
    """A dict of key -> (state, expiry), guarded by one lock.

    One lock is the simplest correct choice: every update is O(1) or O(limit)
    and short. Lock striping is the next step if profiling ever says so.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()  # guards _entries and every state object in it

    def update[R](self, key: str, now: float, ttl: float,
                  step: Callable[[Any | None], tuple[Any, R]]) -> R:
        with self._lock:
            entry = self._entries.get(key)
            state = entry.state if entry is not None and entry.expires_at > now else None
            new_state, result = step(state)
            self._entries[key] = _Entry(new_state, now + ttl)
            return result

    def purge_expired(self, now: float) -> int:
        with self._lock:
            expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
            for key in expired:
                del self._entries[key]
        if expired:
            log.info("purged %d idle rate-limit keys", len(expired))
        return len(expired)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
