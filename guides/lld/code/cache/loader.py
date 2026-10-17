"""Read-through loading with single-flight, so a miss never becomes a stampede.

The stampede: a hot key expires, and 500 requests miss at the same instant.
Without coordination, all 500 call the database for the same row. With
single-flight, the first thread to miss becomes the *leader* and calls the
loader. The other 499 become *followers* and wait on the leader's Future.
One load, 500 answers.

Lock order is always loader lock -> cache lock, never the reverse, so the two
locks cannot deadlock. The loader itself runs with no lock held at all.
"""
import functools
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future

from .cache import MISSING, Cache
from .errors import LoadError

log = logging.getLogger(__name__)


class SingleFlightLoader[K, V]:
    def __init__(self, cache: Cache[K, V], loader: Callable[[K], V], *,
                 ttl: float | None = None) -> None:
        self._cache = cache
        self._loader = loader
        self._ttl = ttl
        self._lock = threading.Lock()  # guards _in_flight and _load_count
        self._in_flight: dict[K, Future[V]] = {}
        self._load_count = 0

    @property
    def load_count(self) -> int:
        """How many times the underlying loader has actually been called."""
        with self._lock:
            return self._load_count

    def get(self, key: K) -> V:
        value = self._cache.get(key, MISSING)
        if value is not MISSING:
            return value  # type: ignore[return-value]

        with self._lock:
            # Re-check: a leader may have finished between our miss and now.
            value = self._cache.peek(key, MISSING)
            if value is not MISSING:
                return value  # type: ignore[return-value]
            future = self._in_flight.get(key)
            is_leader = future is None
            if is_leader:
                future = Future()
                self._in_flight[key] = future
                self._load_count += 1

        if not is_leader:
            return future.result()  # blocks; re-raises the leader's LoadError

        try:
            value = self._loader(key)
            # Store BEFORE leaving the in-flight map, so a late arrival
            # finds the value in the cache instead of starting a second load.
            self._cache.put(key, value, ttl=self._ttl)
        except Exception as exc:
            error = LoadError(f"loading {key!r} failed: {exc}")
            error.__cause__ = exc
            future.set_exception(error)
            raise error from exc
        else:
            future.set_result(value)
            log.debug("loaded %r", key)
            return value
        finally:
            if not future.done():
                # Only on BaseException (e.g. KeyboardInterrupt): never leave
                # followers blocked on a Future nobody will resolve.
                future.set_exception(LoadError(f"loading {key!r} was aborted"))
            with self._lock:
                del self._in_flight[key]


def read_through[K, V](cache: Cache[K, V], *, ttl: float | None = None
                       ) -> Callable[[Callable[[K], V]], Callable[[K], V]]:
    """Decorator: turn a one-argument fetch function into a cached one.

        @read_through(cache, ttl=30)
        def load_user(user_id): ...

    The wrapped function keeps its name and docstring; the SingleFlightLoader
    behind it is reachable as wrapper.single_flight (for load_count in tests).
    """
    def decorate(fetch: Callable[[K], V]) -> Callable[[K], V]:
        flight = SingleFlightLoader(cache, fetch, ttl=ttl)

        @functools.wraps(fetch)
        def wrapper(key: K) -> V:
            return flight.get(key)

        wrapper.single_flight = flight  # type: ignore[attr-defined]
        return wrapper

    return decorate
