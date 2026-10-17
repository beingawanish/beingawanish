"""Retries with backoff and jitter, and a circuit breaker per model.

The retrier retries only errors whose `retryable` flag is set. A 400 fails
fast; a 429 or 529 waits and tries again. The breaker counts only retryable
failures too: a malformed request says nothing about the provider's health.
"""
import logging
import random
import threading
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

from .clock import Clock
from .config import BreakerPolicy, RetryPolicy
from .errors import CircuitOpenError, ProviderError

log = logging.getLogger(__name__)
T = TypeVar("T")


class Retrier:
    def __init__(self, policy: RetryPolicy, clock: Clock, rng: random.Random) -> None:
        self._policy = policy
        self._clock = clock
        self._rng = rng

    def delay_for(self, attempt: int, error: ProviderError) -> float:
        """Full jitter: uniform in [0, min(max, base * 2**attempt)].
        A provider's retry-after hint wins when it gives one."""
        if error.retry_after_s is not None:
            return error.retry_after_s
        ceiling = min(self._policy.max_delay_s, self._policy.base_delay_s * 2 ** attempt)
        return self._rng.uniform(0.0, ceiling)

    def run(self, operation: Callable[[], T]) -> T:
        for attempt in range(self._policy.max_attempts):
            try:
                return operation()
            except ProviderError as err:
                last_try = attempt == self._policy.max_attempts - 1
                if not err.retryable or last_try:
                    raise
                delay = self.delay_for(attempt, err)
                if delay > self._policy.max_delay_s:
                    log.info("retry-after %.1fs exceeds max wait; giving up", delay)
                    raise
                log.info("attempt %d failed (%s); retrying in %.3fs",
                         attempt + 1, type(err).__name__, delay)
                self._clock.sleep(delay)
        raise AssertionError("unreachable: the loop returns or raises")


class BreakerState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """CLOSED -> OPEN after `failure_threshold` consecutive retryable failures.
    OPEN -> HALF_OPEN once `cooldown_s` has passed; exactly one trial call goes
    through. Trial success closes the circuit; trial failure reopens it.
    The lock guards state, the failure count and the trial flag."""

    def __init__(self, name: str, policy: BreakerPolicy, clock: Clock) -> None:
        self.name = name
        self._policy = policy
        self._clock = clock
        self._lock = threading.Lock()
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> BreakerState:
        with self._lock:
            return self._current_state()

    def call(self, operation: Callable[[], T]) -> T:
        self._before_call()
        try:
            result = operation()
        except ProviderError as err:
            self._after_failure(err)
            raise
        self._after_success()
        return result

    def _current_state(self) -> BreakerState:
        cooled = self._clock.now() - self._opened_at >= self._policy.cooldown_s
        if self._state is BreakerState.OPEN and cooled:
            self._state = BreakerState.HALF_OPEN
        return self._state

    def _before_call(self) -> None:
        with self._lock:
            state = self._current_state()
            if state is BreakerState.OPEN:
                raise CircuitOpenError(f"circuit for {self.name} is open")
            if state is BreakerState.HALF_OPEN:
                if self._trial_in_flight:
                    raise CircuitOpenError(f"circuit for {self.name} is testing")
                self._trial_in_flight = True

    def _after_success(self) -> None:
        with self._lock:
            if self._state is not BreakerState.CLOSED:
                log.info("circuit for %s closed", self.name)
            self._state = BreakerState.CLOSED
            self._failures = 0
            self._trial_in_flight = False

    def _after_failure(self, err: ProviderError) -> None:
        with self._lock:
            self._trial_in_flight = False
            if not err.retryable:
                return
            self._failures += 1
            trial_failed = self._state is BreakerState.HALF_OPEN
            if trial_failed or self._failures >= self._policy.failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = self._clock.now()
                log.warning("circuit for %s opened after %d failures", self.name, self._failures)
