"""The rate limiter: resolve the rule, run the algorithm in the store, decide.

It holds no mutable state of its own. All per-key state lives in the store,
which is what makes the same class work in one process or across a fleet.
"""
import logging
import threading
from collections.abc import Mapping

from .algorithms import RateLimitAlgorithm, default_algorithms
from .clock import Clock, MonotonicClock
from .config import LimitRule, RateLimiterConfig
from .decision import Decision
from .errors import (
    ConfigError,
    InvalidCostError,
    LimiterUnavailableError,
    StoreError,
    UnknownAlgorithmError,
)
from .rules import ClientKey, RuleBook
from .store import InMemoryStore, StateStore

log = logging.getLogger(__name__)


class RateLimiter:
    def __init__(
        self,
        config: RateLimiterConfig | None = None,
        *,
        store: StateStore | None = None,
        clock: Clock | None = None,
        algorithms: Mapping[str, RateLimitAlgorithm] | None = None,
    ) -> None:
        # `is None`, not `or`: an empty store defines __len__ == 0, so it is falsy.
        self._config = config if config is not None else RateLimiterConfig()
        self._store = store if store is not None else InMemoryStore()
        self._clock = clock if clock is not None else MonotonicClock()
        self._algorithms = dict(algorithms) if algorithms is not None else default_algorithms()
        self._rules = RuleBook(self._config)
        for rule in self._rules.rules():  # fail at startup, not on the first request
            if rule.algorithm not in self._algorithms:
                raise UnknownAlgorithmError(f"{rule.name}: no algorithm named {rule.algorithm!r}")

    def check(self, client: ClientKey, cost: int = 1) -> Decision:
        """Decide one request of `cost` units for `client`, and record it if allowed."""
        rule = self._rules.rule_for(client)
        if not 1 <= cost <= rule.capacity:
            raise InvalidCostError(f"cost must be between 1 and {rule.capacity}, got {cost}")
        algorithm = self._algorithms[rule.algorithm]
        now = self._clock.now()
        ttl = algorithm.idle_ttl(rule) + self._config.idle_grace_seconds
        try:
            decision = self._store.update(
                client.storage_key(rule), now, ttl,
                lambda state: algorithm.apply(state, rule, now, cost),
            )
        except StoreError as exc:
            return self._on_store_failure(rule, exc)
        if not decision.allowed:
            # DEBUG, not INFO: a client hammering a 429 would flood the logs.
            log.debug("denied %s:%s on %s, retry in %.3fs",
                      client.scope, client.value, rule.name, decision.retry_after)
        return decision

    @property
    def config(self) -> RateLimiterConfig:
        return self._config

    def sweep_idle(self) -> int:
        """Purge keys idle past their reset point. Returns how many were removed."""
        return self._store.purge_expired(self._clock.now())

    def _on_store_failure(self, rule: LimitRule, exc: StoreError) -> Decision:
        if self._config.fail_open:
            log.warning("rate-limit store failed, failing open for %s: %s", rule.name, exc)
            return Decision(True, rule.capacity, rule.capacity, 0.0, 0.0, degraded=True)
        log.error("rate-limit store failed, failing closed for %s: %s", rule.name, exc)
        raise LimiterUnavailableError(f"rate-limit store unavailable: {exc}") from exc


class IdleKeySweeper:
    """Background thread that calls limiter.sweep_idle() every interval.

    Use as a context manager, or call start() and stop() yourself.
    """

    def __init__(self, limiter: RateLimiter, interval_seconds: float | None = None) -> None:
        interval = limiter.config.sweep_interval_seconds if interval_seconds is None else interval_seconds
        if interval <= 0:
            raise ConfigError(f"sweep interval must be > 0, got {interval}")
        self._limiter = limiter
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("sweeper already started")
        self._thread = threading.Thread(target=self._run, name="rate-limit-sweeper", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._limiter.sweep_idle()
            except StoreError:
                log.exception("idle-key sweep failed; will retry next interval")

    def __enter__(self) -> "IdleKeySweeper":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
