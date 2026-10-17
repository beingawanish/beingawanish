"""Five rate-limiting algorithms behind one interface.

Each algorithm is a pure function of (old state, rule, now, cost) to
(new state, decision). No clock, no lock, no I/O. That purity is what lets the
same step run inside an in-memory lock today and inside a Redis Lua script later.
"""
import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass

from .config import Algorithm, LimitRule
from .decision import Decision


class RateLimitAlgorithm[S](ABC):
    """The contract every algorithm honours.

    apply()    -- decide one request and return the key's next state.
                  `state` is None for a key never seen (or already expired).
    idle_ttl() -- seconds after a key's last request at which its state is
                  indistinguishable from a fresh key. Past that, it can be deleted.
    """

    name: str

    @abstractmethod
    def apply(self, state: S | None, rule: LimitRule, now: float, cost: int) -> tuple[S, Decision]:
        ...

    @abstractmethod
    def idle_ttl(self, rule: LimitRule) -> float:
        ...


def _allow(rule: LimitRule, remaining: float, reset_after: float, delay: float = 0.0) -> Decision:
    return Decision(True, rule.capacity, max(0, math.floor(remaining)), 0.0, reset_after, delay)


def _deny(rule: LimitRule, remaining: float, retry_after: float, reset_after: float) -> Decision:
    return Decision(False, rule.capacity, max(0, math.floor(remaining)), retry_after, reset_after)


# --------------------------------------------------------------------------- buckets

@dataclass(frozen=True, slots=True)
class BucketState:
    level: float        # tokens left (token bucket) or water held (leaky bucket)
    updated_at: float


class TokenBucket(RateLimitAlgorithm[BucketState]):
    """A bucket of `capacity` tokens refilling at `rate_per_second`.

    Allows bursts up to capacity, then the average rate. Two floats per key.
    """

    name = Algorithm.TOKEN_BUCKET

    def apply(self, state: BucketState | None, rule: LimitRule, now: float,
              cost: int) -> tuple[BucketState, Decision]:
        capacity, rate = rule.capacity, rule.rate_per_second
        if state is None:
            tokens = float(capacity)
        else:
            elapsed = max(0.0, now - state.updated_at)  # never refill on a clock step back
            tokens = min(float(capacity), state.level + elapsed * rate)
        if tokens >= cost:
            tokens -= cost
            decision = _allow(rule, tokens, (capacity - tokens) / rate)
        else:
            decision = _deny(rule, tokens, (cost - tokens) / rate, (capacity - tokens) / rate)
        return BucketState(tokens, now), decision

    def idle_ttl(self, rule: LimitRule) -> float:
        return rule.capacity / rule.rate_per_second


class LeakyBucket(RateLimitAlgorithm[BucketState]):
    """A queue of `capacity` slots draining at `rate_per_second`.

    It shapes rather than polices: an admitted request gets a `delay`, the time
    its place in the queue takes to reach the front. Output is perfectly smooth.
    """

    name = Algorithm.LEAKY_BUCKET

    def apply(self, state: BucketState | None, rule: LimitRule, now: float,
              cost: int) -> tuple[BucketState, Decision]:
        capacity, rate = rule.capacity, rule.rate_per_second
        if state is None:
            level = 0.0
        else:
            elapsed = max(0.0, now - state.updated_at)
            level = max(0.0, state.level - elapsed * rate)
        if level + cost <= capacity:
            delay = level / rate
            level += cost
            decision = _allow(rule, capacity - level, level / rate, delay)
        else:
            decision = _deny(rule, capacity - level, (level + cost - capacity) / rate, level / rate)
        return BucketState(level, now), decision

    def idle_ttl(self, rule: LimitRule) -> float:
        return rule.capacity / rule.rate_per_second


# --------------------------------------------------------------------------- windows

@dataclass(frozen=True, slots=True)
class WindowState:
    window: int         # index of the window: floor(now / window_seconds)
    count: int


class FixedWindow(RateLimitAlgorithm[WindowState]):
    """A counter per aligned window. Cheapest of all, but up to 2x the limit
    can pass across a window boundary."""

    name = Algorithm.FIXED_WINDOW

    def apply(self, state: WindowState | None, rule: LimitRule, now: float,
              cost: int) -> tuple[WindowState, Decision]:
        size = rule.window_seconds
        window = math.floor(now / size)
        count = state.count if state is not None and state.window == window else 0
        until_next = (window + 1) * size - now
        if count + cost <= rule.limit:
            count += cost
            decision = _allow(rule, rule.limit - count, until_next)
        else:
            decision = _deny(rule, rule.limit - count, until_next, until_next)
        return WindowState(window, count), decision

    def idle_ttl(self, rule: LimitRule) -> float:
        return rule.window_seconds


@dataclass(slots=True)
class LogState:
    stamps: deque[float]   # one timestamp per admitted unit of cost, oldest first


class SlidingWindowLog(RateLimitAlgorithm[LogState]):
    """Exact: remembers every admitted request in the last window.

    Memory is O(limit) per key, so it suits small limits only.
    The deque is mutated in place; the store calls apply() under its lock.
    """

    name = Algorithm.SLIDING_LOG

    def apply(self, state: LogState | None, rule: LimitRule, now: float,
              cost: int) -> tuple[LogState, Decision]:
        size = rule.window_seconds
        stamps = deque() if state is None else state.stamps
        while stamps and stamps[0] <= now - size:   # the window is (now - size, now]
            stamps.popleft()
        if len(stamps) + cost <= rule.limit:
            stamps.extend([now] * cost)
            decision = _allow(rule, rule.limit - len(stamps), stamps[-1] + size - now)
        else:
            # The request fits once enough of the oldest entries have aged out.
            must_expire = len(stamps) + cost - rule.limit
            retry_after = stamps[must_expire - 1] + size - now
            decision = _deny(rule, rule.limit - len(stamps), retry_after, stamps[-1] + size - now)
        return LogState(stamps), decision

    def idle_ttl(self, rule: LimitRule) -> float:
        return rule.window_seconds


@dataclass(frozen=True, slots=True)
class CounterState:
    window: int
    current: int        # admitted in the current window
    previous: int       # admitted in the window before it


class SlidingWindowCounter(RateLimitAlgorithm[CounterState]):
    """Two counters and a weighted estimate of the sliding window.

    estimate = previous * (share of the previous window still inside the
    sliding window) + current. Near-exact, and O(1) memory per key.
    """

    name = Algorithm.SLIDING_COUNTER

    def apply(self, state: CounterState | None, rule: LimitRule, now: float,
              cost: int) -> tuple[CounterState, Decision]:
        size = rule.window_seconds
        window = math.floor(now / size)
        if state is None or state.window < window - 1:
            current, previous = 0, 0
        elif state.window == window - 1:
            current, previous = 0, state.current
        else:
            current, previous = state.current, state.previous
        elapsed = now - window * size
        estimate = previous * (size - elapsed) / size + current
        if estimate + cost <= rule.limit:
            current += cost
            decision = _allow(rule, rule.limit - estimate - cost,
                              self._reset_after(current, previous, elapsed, size))
        else:
            retry_after = self._retry_after(current, previous, elapsed, size, rule.limit, cost)
            decision = _deny(rule, rule.limit - estimate, retry_after,
                             self._reset_after(current, previous, elapsed, size))
        return CounterState(window, current, previous), decision

    @staticmethod
    def _retry_after(current: int, previous: int, elapsed: float, size: float,
                     limit: int, cost: int) -> float:
        room = limit - cost - current
        if room >= 0 and previous > 0:
            # Fits later in this window, once the previous window's weight decays:
            # previous * (size - t) / size <= room.
            return size * (1 - room / previous) - elapsed
        until_next = size - elapsed
        room_next = limit - cost
        if current <= room_next:
            return until_next
        # In the next window, this window's count decays the same way.
        return until_next + size * (1 - room_next / current)

    @staticmethod
    def _reset_after(current: int, previous: int, elapsed: float, size: float) -> float:
        if current > 0:
            return 2 * size - elapsed
        if previous > 0:
            return size - elapsed
        return 0.0

    def idle_ttl(self, rule: LimitRule) -> float:
        return 2 * rule.window_seconds


def default_algorithms() -> dict[str, RateLimitAlgorithm]:
    """The built-in registry, keyed by Algorithm name."""
    algorithms: tuple[RateLimitAlgorithm, ...] = (
        TokenBucket(), LeakyBucket(), FixedWindow(), SlidingWindowLog(), SlidingWindowCounter(),
    )
    return {algorithm.name: algorithm for algorithm in algorithms}
