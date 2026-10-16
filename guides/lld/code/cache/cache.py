"""The cache itself: O(1) get/put, TTL, two capacity limits, stats, listeners.

Division of labour:
  - the dict below holds values (key -> entry), so lookup is O(1);
  - the policy holds the order of keys and picks eviction victims in O(1);
  - the clock says what time it is; the sizer says how big a value is;
  - listeners hear about removals after the lock is released.

Expiry is lazy: get() notices a dead entry and removes it on the spot.
purge_expired() does the same for every entry; a Sweeper calls it on a timer.

Thread safety: one lock guards _entries, _total_size, _stats and the policy.
Every public method takes it, so each call is atomic. Listener callbacks are
collected under the lock and fired after it is released.
"""
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from .clock import Clock, SystemClock
from .config import CacheConfig
from .errors import EntryTooLargeError, InvalidEntryError
from .listeners import EvictionListener, RemovalCause, RemovalNotification
from .policies import EvictionPolicy, make_policy
from .stats import CacheStats, StatsCounter

log = logging.getLogger(__name__)


class _Missing:
    """Sentinel type: lets None be a legitimate cached value."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Final = _Missing()


def unit_size(value: object) -> int:
    """Default sizer: every entry counts as 1, so max_size acts like a count."""
    return 1


@dataclass(slots=True)
class _Entry[V]:
    value: V
    size: int
    expires_at: float | None  # monotonic seconds; None = never

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and now >= self.expires_at


class Cache[K, V]:
    def __init__(
        self,
        config: CacheConfig | None = None,
        *,
        policy: EvictionPolicy[K] | None = None,
        clock: Clock | None = None,
        sizer: Callable[[V], int] | None = None,
        listeners: Iterable[EvictionListener[K, V]] = (),
    ) -> None:
        self._config = config or CacheConfig()
        self._policy = policy or make_policy(self._config.eviction)
        self._clock = clock or SystemClock()
        self._sizer = sizer or unit_size
        self._listeners = list(listeners)
        self._lock = threading.Lock()  # guards everything below this line
        self._entries: dict[K, _Entry[V]] = {}
        self._total_size = 0
        self._stats = StatsCounter()

    @property
    def config(self) -> CacheConfig:
        return self._config

    # -- reads ----------------------------------------------------------

    def get(self, key: K, default: V | None = None) -> V | None:
        """Value for key, or default. Counts a hit or a miss; refreshes recency."""
        removed: list[RemovalNotification[K, V]] = []
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.is_expired(self._clock.now()):
                self._remove(key, RemovalCause.EXPIRED, removed)
                entry = None
            if entry is None:
                self._stats.misses += 1
                result = default
            else:
                self._stats.hits += 1
                self._policy.on_access(key)
                result = entry.value
        self._notify(removed)
        return result

    def peek(self, key: K, default: V | None = None) -> V | None:
        """Like get(), with no side effects: no stats, no recency, no removal."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.is_expired(self._clock.now()):
                return default
            return entry.value

    def __contains__(self, key: object) -> bool:
        return self.peek(key, MISSING) is not MISSING  # type: ignore[arg-type]

    def __len__(self) -> int:
        """Stored entries, including expired ones not yet noticed."""
        with self._lock:
            return len(self._entries)

    @property
    def total_size(self) -> int:
        with self._lock:
            return self._total_size

    def stats(self) -> CacheStats:
        with self._lock:
            return self._stats.snapshot()

    # -- writes ---------------------------------------------------------

    def put(self, key: K, value: V, *, ttl: float | None = None,
            size: int | None = None) -> None:
        """Store value. ttl overrides config.default_ttl; size overrides the sizer.

        Overwriting a key replaces the entry as if it were new: it goes to the
        front of LRU and FIFO order and restarts at count 1 under LFU.
        """
        if ttl is not None and ttl <= 0:
            raise InvalidEntryError(f"ttl must be > 0, got {ttl}")
        size = self._sizer(value) if size is None else size
        if size < 0:
            raise InvalidEntryError(f"size must be >= 0, got {size}")
        max_size = self._config.max_size
        if max_size is not None and size > max_size:
            raise EntryTooLargeError(
                f"entry of size {size} can never fit in max_size {max_size}")
        ttl = self._config.default_ttl if ttl is None else ttl

        removed: list[RemovalNotification[K, V]] = []
        with self._lock:
            now = self._clock.now()
            if key in self._entries:
                self._remove(key, RemovalCause.REPLACED, removed)
            self._make_room(size, removed)
            self._entries[key] = _Entry(
                value, size, None if ttl is None else now + ttl)
            self._total_size += size
            self._policy.on_insert(key)
            self._stats.puts += 1
        self._notify(removed)

    def delete(self, key: K) -> bool:
        """Remove key. True if it was there (even if already expired)."""
        removed: list[RemovalNotification[K, V]] = []
        with self._lock:
            if key in self._entries:
                self._remove(key, RemovalCause.EXPLICIT, removed)
        self._notify(removed)
        return bool(removed)

    def clear(self) -> None:
        removed: list[RemovalNotification[K, V]] = []
        with self._lock:
            for key in list(self._entries):
                self._remove(key, RemovalCause.EXPLICIT, removed)
        self._notify(removed)

    def purge_expired(self) -> int:
        """Remove every expired entry now. O(n); meant for a background sweeper."""
        removed: list[RemovalNotification[K, V]] = []
        with self._lock:
            now = self._clock.now()
            dead = [k for k, e in self._entries.items() if e.is_expired(now)]
            for key in dead:
                self._remove(key, RemovalCause.EXPIRED, removed)
        self._notify(removed)
        if removed:
            log.debug("purged %d expired entries", len(removed))
        return len(removed)

    # -- internals (call with the lock held) ----------------------------

    def _make_room(self, incoming_size: int,
                   removed: list[RemovalNotification[K, V]]) -> None:
        max_size = self._config.max_size
        while self._entries and (
            len(self._entries) + 1 > self._config.max_entries
            or (max_size is not None
                and self._total_size + incoming_size > max_size)
        ):
            self._remove(self._policy.victim(), RemovalCause.CAPACITY, removed)

    def _remove(self, key: K, cause: RemovalCause,
                removed: list[RemovalNotification[K, V]]) -> None:
        entry = self._entries.pop(key)
        self._total_size -= entry.size
        self._policy.on_remove(key)
        if cause is RemovalCause.CAPACITY:
            self._stats.evictions += 1
        elif cause is RemovalCause.EXPIRED:
            self._stats.expirations += 1
        removed.append(RemovalNotification(key, entry.value, cause))

    # -- listeners (call WITHOUT the lock) ------------------------------

    def _notify(self, removed: list[RemovalNotification[K, V]]) -> None:
        for notification in removed:
            for listener in self._listeners:
                try:
                    listener.on_removal(notification)
                except Exception:
                    # One broken listener must not break the cache or starve
                    # the others. Log it with the traceback and move on.
                    log.exception("eviction listener %r failed on %r",
                                  listener, notification.key)
