"""Optional background sweeper: purges expired entries on a timer.

Lazy expiry alone has a blind spot. An entry nobody reads again is never
looked at, so it sits in memory until capacity pressure evicts it. The
sweeper closes that gap. It is optional because many caches never need it.
"""
import logging
import threading
from types import TracebackType

from .cache import Cache
from .errors import SweeperStateError

log = logging.getLogger(__name__)


class Sweeper:
    def __init__(self, cache: Cache, interval: float) -> None:
        if interval <= 0:
            raise ValueError(f"interval must be > 0, got {interval}")
        self._cache = cache
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sweep_once(self) -> int:
        """One pass. Tests call this directly for deterministic sweeps."""
        try:
            return self._cache.purge_expired()
        except Exception:
            # A background thread has no caller to raise to. If it died here,
            # sweeping would stop silently forever. Log loudly, try again later.
            log.exception("sweep failed; will retry next interval")
            return 0

    def start(self) -> None:
        if self._thread is not None:
            raise SweeperStateError("sweeper already started")
        self._thread = threading.Thread(
            target=self._run, name="cache-sweeper", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        if self._thread is None:
            raise SweeperStateError("sweeper was never started")
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        # Event.wait doubles as an interruptible sleep: stop() wakes it at once.
        while not self._stop.wait(self._interval):
            self.sweep_once()

    def __enter__(self) -> "Sweeper":
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None, tb: TracebackType | None) -> None:
        self.stop()
