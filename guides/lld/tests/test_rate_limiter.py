"""Tests for the rate limiter. Time is a ManualClock throughout; nothing sleeps
except the one test that exercises the real background sweeper thread."""
import threading
import time
import unittest

from rate_limiter import (
    Algorithm,
    ClientKey,
    ConfigError,
    Decision,
    IdleKeySweeper,
    InMemoryStore,
    InvalidCostError,
    InvalidKeyError,
    InvalidRuleError,
    KeyScope,
    LimitRule,
    LimiterUnavailableError,
    ManualClock,
    RateLimitAlgorithm,
    RateLimiter,
    RateLimiterConfig,
    StoreError,
    TokenBucket,
    UnknownAlgorithmError,
    UnknownTierError,
)

START = 1_000.0          # a window boundary for every window size used below
LIMIT, WINDOW = 5, 10.0  # the contract tests' rule: 5 requests per 10 seconds
TINY = 1e-6
USER = ClientKey(KeyScope.USER, "alice")


def make_limiter(rule, clock=None, store=None, **config_kwargs):
    clock = clock or ManualClock(START)
    config = RateLimiterConfig(
        tiers={rule.name: rule},
        default_tier_by_scope={scope: rule.name for scope in KeyScope},
        **config_kwargs,
    )
    return RateLimiter(config, clock=clock, store=store), clock


def drain(limiter, client=USER, n=LIMIT):
    return [limiter.check(client) for _ in range(n)]


class AlgorithmContractTests(unittest.TestCase):
    """Liskov in practice: every algorithm must pass the same behavioural contract."""

    def each_algorithm(self):
        for algorithm in Algorithm:
            with self.subTest(algorithm=algorithm):
                yield make_limiter(LimitRule("t", LIMIT, WINDOW, algorithm))

    def test_fresh_key_allows_exactly_the_limit_then_denies(self):
        for limiter, _ in self.each_algorithm():
            self.assertTrue(all(d.allowed for d in drain(limiter)))
            denied = limiter.check(USER)
            self.assertFalse(denied.allowed)
            self.assertEqual(denied.status_code, 429)

    def test_retry_after_is_exact(self):
        for limiter, clock in self.each_algorithm():
            drain(limiter)
            retry_after = limiter.check(USER).retry_after
            self.assertGreater(retry_after, 0)
            clock.advance(retry_after - 0.01)
            self.assertFalse(limiter.check(USER).allowed, "too early must still be denied")
            clock.advance(0.01 + TINY)
            self.assertTrue(limiter.check(USER).allowed, "at retry_after it must pass")

    def test_full_quota_returns_after_idle_ttl(self):
        for limiter, clock in self.each_algorithm():
            drain(limiter)
            clock.advance(2 * WINDOW)
            self.assertTrue(all(d.allowed for d in drain(limiter)))

    def test_keys_are_independent(self):
        for limiter, _ in self.each_algorithm():
            drain(limiter)
            self.assertTrue(limiter.check(ClientKey(KeyScope.USER, "bob")).allowed)

    def test_decision_invariants(self):
        for limiter, _ in self.each_algorithm():
            for d in drain(limiter, n=LIMIT + 2):
                self.assertTrue(0 <= d.remaining <= d.limit)
                self.assertGreaterEqual(d.reset_after, 0)
                self.assertEqual(d.retry_after == 0, d.allowed)


class TokenBucketTests(unittest.TestCase):
    def test_refills_at_the_average_rate(self):
        limiter, clock = make_limiter(LimitRule("t", 5, 10.0))  # 0.5 tokens/s
        drain(limiter)
        clock.advance(4.0)  # two tokens back
        self.assertEqual([d.allowed for d in drain(limiter, n=3)], [True, True, False])

    def test_burst_is_separate_from_rate(self):
        limiter, _ = make_limiter(LimitRule("t", 5, 10.0, burst=8))
        results = drain(limiter, n=9)
        self.assertEqual(sum(d.allowed for d in results), 8)
        self.assertEqual(results[0].limit, 8)

    def test_cost_consumes_several_tokens(self):
        limiter, _ = make_limiter(LimitRule("t", 5, 10.0))
        self.assertEqual(limiter.check(USER, cost=4).remaining, 1)
        denied = limiter.check(USER, cost=3)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.remaining, 1)
        self.assertAlmostEqual(denied.retry_after, 4.0)  # 2 missing tokens at 0.5/s

    def test_clock_step_back_never_adds_tokens(self):
        algorithm = TokenBucket()
        rule = LimitRule("t", 5, 10.0)
        state, _ = algorithm.apply(None, rule, 100.0, 5)
        _, decision = algorithm.apply(state, rule, 90.0, 1)
        self.assertFalse(decision.allowed)


class LeakyBucketTests(unittest.TestCase):
    def test_admitted_requests_are_queued_with_growing_delay(self):
        limiter, _ = make_limiter(LimitRule("t", 1, 1.0, Algorithm.LEAKY_BUCKET, burst=3))
        results = drain(limiter, n=4)
        self.assertEqual([d.delay for d in results[:3]], [0.0, 1.0, 2.0])
        self.assertFalse(results[3].allowed)
        self.assertAlmostEqual(results[3].retry_after, 1.0)

    def test_queue_drains_over_time(self):
        limiter, clock = make_limiter(LimitRule("t", 1, 1.0, Algorithm.LEAKY_BUCKET, burst=3))
        drain(limiter, n=3)
        clock.advance(2.0)
        decision = limiter.check(USER)
        self.assertTrue(decision.allowed)
        self.assertAlmostEqual(decision.delay, 1.0)


class FixedWindowTests(unittest.TestCase):
    def test_counter_resets_at_the_boundary(self):
        limiter, clock = make_limiter(LimitRule("t", 5, 10.0, Algorithm.FIXED_WINDOW))
        clock.advance(3.0)
        drain(limiter)
        denied = limiter.check(USER)
        self.assertAlmostEqual(denied.retry_after, 7.0)
        clock.advance(7.0)
        self.assertTrue(limiter.check(USER).allowed)

    def test_boundary_burst_lets_twice_the_limit_through(self):
        """The known weakness, pinned so nobody 'discovers' it in production."""
        limiter, clock = make_limiter(
            LimitRule("t", 5, 10.0, Algorithm.FIXED_WINDOW), clock=ManualClock(START - 0.1))
        allowed = sum(d.allowed for d in drain(limiter))
        clock.advance(0.2)
        allowed += sum(d.allowed for d in drain(limiter))
        self.assertEqual(allowed, 10)


class SlidingWindowLogTests(unittest.TestCase):
    def test_boundary_burst_is_blocked(self):
        limiter, clock = make_limiter(
            LimitRule("t", 5, 10.0, Algorithm.SLIDING_LOG), clock=ManualClock(START - 0.1))
        drain(limiter)
        clock.advance(0.2)
        self.assertFalse(any(d.allowed for d in drain(limiter)))

    def test_each_entry_expires_exactly_one_window_later(self):
        limiter, clock = make_limiter(LimitRule("t", 2, 10.0, Algorithm.SLIDING_LOG))
        limiter.check(USER)
        clock.advance(4.0)
        limiter.check(USER)
        denied = limiter.check(USER)
        self.assertAlmostEqual(denied.retry_after, 6.0)  # the t=0 entry leaves at t=10
        clock.advance(6.0)  # an entry exactly one window old is out
        self.assertTrue(limiter.check(USER).allowed)
        self.assertFalse(limiter.check(USER).allowed)


class SlidingWindowCounterTests(unittest.TestCase):
    def test_previous_window_is_weighted_by_overlap(self):
        limiter, clock = make_limiter(LimitRule("t", 10, 10.0, Algorithm.SLIDING_COUNTER))
        drain(limiter, n=10)
        clock.advance(17.0)  # previous=10, 30% of it still overlaps: estimate 3
        results = drain(limiter, n=8)
        self.assertEqual(sum(d.allowed for d in results), 7)

    def test_boundary_burst_is_blocked(self):
        limiter, clock = make_limiter(
            LimitRule("t", 5, 10.0, Algorithm.SLIDING_COUNTER), clock=ManualClock(START - 0.1))
        drain(limiter)
        clock.advance(0.2)
        self.assertFalse(any(d.allowed for d in drain(limiter)))

    def test_two_idle_windows_forget_everything(self):
        limiter, clock = make_limiter(LimitRule("t", 5, 10.0, Algorithm.SLIDING_COUNTER))
        drain(limiter)
        clock.advance(20.0)
        self.assertEqual(limiter.check(USER).remaining, 4)


class DecisionTests(unittest.TestCase):
    def test_allowed_headers(self):
        d = Decision(True, 100, 42, 0.0, 12.2)
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.headers(), {"RateLimit-Limit": "100", "RateLimit-Remaining": "42",
                                       "RateLimit-Reset": "13"})

    def test_denied_headers_round_up_and_never_say_zero(self):
        d = Decision(False, 100, 0, 0.2, 30.0)
        self.assertEqual(d.status_code, 429)
        self.assertEqual(d.headers()["Retry-After"], "1")
        self.assertEqual(Decision(False, 1, 0, 2.0000000001, 2.0).headers()["Retry-After"], "2")

    def test_degraded_decision_sends_no_headers(self):
        self.assertEqual(Decision(True, 5, 5, 0.0, 0.0, degraded=True).headers(), {})


class ConfigAndRuleTests(unittest.TestCase):
    def test_invalid_rules_are_rejected(self):
        for kwargs in ({"limit": 0, "window_seconds": 1.0},
                       {"limit": 1, "window_seconds": 0.0},
                       {"limit": 1, "window_seconds": 1.0, "algorithm": Algorithm.FIXED_WINDOW,
                        "burst": 5},
                       {"limit": 1, "window_seconds": 1.0, "burst": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(InvalidRuleError):
                LimitRule("bad", **kwargs)

    def test_config_rejects_dangling_tiers(self):
        rule = LimitRule("free", 5, 10.0)
        with self.assertRaises(ConfigError):
            RateLimiterConfig(tiers={"free": rule}, default_tier_by_scope={KeyScope.IP: "gold"})
        with self.assertRaises(ConfigError):
            RateLimiterConfig(tiers={"paid": rule})

    def test_default_tiers_by_scope(self):
        limiter = RateLimiter(clock=ManualClock(START))
        self.assertEqual(limiter.check(ClientKey(KeyScope.IP, "198.51.100.4")).limit, 30)
        self.assertEqual(limiter.check(ClientKey(KeyScope.API_KEY, "k1")).limit, 100)
        self.assertEqual(limiter.check(ClientKey(KeyScope.USER, "u1", tier="pro")).limit, 2_000)

    def test_unknown_tier_and_blank_key_are_rejected(self):
        limiter = RateLimiter(clock=ManualClock(START))
        with self.assertRaises(UnknownTierError):
            limiter.check(ClientKey(KeyScope.USER, "u1", tier="platinum"))
        with self.assertRaises(InvalidKeyError):
            ClientKey(KeyScope.IP, "   ")

    def test_same_value_in_different_scopes_is_counted_separately(self):
        limiter, _ = make_limiter(LimitRule("t", 1, 10.0))
        self.assertTrue(limiter.check(ClientKey(KeyScope.USER, "x")).allowed)
        self.assertTrue(limiter.check(ClientKey(KeyScope.API_KEY, "x")).allowed)

    def test_cost_outside_bounds_is_rejected(self):
        limiter, _ = make_limiter(LimitRule("t", 5, 10.0))
        for cost in (0, 6):
            with self.subTest(cost=cost), self.assertRaises(InvalidCostError):
                limiter.check(USER, cost=cost)


class AlwaysAllow(RateLimitAlgorithm[None]):
    name = "always_allow"

    def apply(self, state, rule, now, cost):
        return None, Decision(True, rule.capacity, rule.capacity, 0.0, 0.0)

    def idle_ttl(self, rule):
        return 0.0


class ExtensionTests(unittest.TestCase):
    def test_custom_algorithm_plugs_in_without_edits(self):
        rule = LimitRule("internal", 1, 1.0, algorithm="always_allow")
        config = RateLimiterConfig(tiers={"internal": rule},
                                   default_tier_by_scope={KeyScope.USER: "internal"})
        limiter = RateLimiter(config, algorithms={"always_allow": AlwaysAllow()})
        self.assertTrue(all(limiter.check(USER).allowed for _ in range(10)))

    def test_unregistered_algorithm_fails_at_startup(self):
        rule = LimitRule("internal", 1, 1.0, algorithm="gcra")
        config = RateLimiterConfig(tiers={"internal": rule}, default_tier_by_scope={})
        with self.assertRaises(UnknownAlgorithmError):
            RateLimiter(config)


class FailingStore(InMemoryStore):
    def update(self, key, now, ttl, step):
        raise StoreError("connection refused")


class StoreAndCleanupTests(unittest.TestCase):
    def test_sweep_removes_only_idle_keys(self):
        limiter, clock = make_limiter(LimitRule("t", 5, 60.0), idle_grace_seconds=5.0)
        limiter.check(ClientKey(KeyScope.IP, "a"))
        clock.advance(30.0)
        limiter.check(ClientKey(KeyScope.IP, "b"))
        clock.advance(40.0)  # a idle 70s > 65s ttl; b idle 40s
        self.assertEqual(limiter.sweep_idle(), 1)
        self.assertEqual(limiter.sweep_idle(), 0)

    def test_expired_entry_reads_as_a_fresh_key(self):
        store = InMemoryStore()
        store.update("k", 0.0, 10.0, lambda state: ("old", None))
        seen = store.update("k", 10.0, 10.0, lambda state: (state, state))
        self.assertIsNone(seen)

    def test_background_sweeper_purges(self):
        store = InMemoryStore()
        limiter, clock = make_limiter(LimitRule("t", 5, 10.0), store=store,
                                      idle_grace_seconds=0.0)
        limiter.check(USER)
        clock.advance(11.0)
        with IdleKeySweeper(limiter, interval_seconds=0.01):
            deadline = time.monotonic() + 2.0
            while len(store) and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(store), 0)

    def test_fail_open_allows_with_no_headers(self):
        config = RateLimiterConfig(tiers={"t": LimitRule("t", 5, 10.0)},
                                   default_tier_by_scope={KeyScope.USER: "t"})
        limiter = RateLimiter(config, store=FailingStore())
        with self.assertLogs("rate_limiter.limiter", "WARNING"):
            decision = limiter.check(USER)
        self.assertTrue(decision.allowed and decision.degraded)
        self.assertEqual(decision.headers(), {})

    def test_fail_closed_raises(self):
        config = RateLimiterConfig(tiers={"t": LimitRule("t", 5, 10.0)},
                                   default_tier_by_scope={KeyScope.USER: "t"}, fail_open=False)
        limiter = RateLimiter(config, store=FailingStore())
        with self.assertLogs("rate_limiter.limiter", "ERROR"), \
                self.assertRaises(LimiterUnavailableError):
            limiter.check(USER)


class ConcurrencyTests(unittest.TestCase):
    def test_exactly_the_limit_passes_under_contention(self):
        threads_count, limit = 40, 10
        for algorithm in Algorithm:
            with self.subTest(algorithm=algorithm):
                limiter, _ = make_limiter(LimitRule("t", limit, 60.0, algorithm))
                barrier = threading.Barrier(threads_count)
                results: list[bool] = []
                results_lock = threading.Lock()

                def hit():
                    barrier.wait()
                    allowed = limiter.check(USER).allowed
                    with results_lock:
                        results.append(allowed)

                workers = [threading.Thread(target=hit) for _ in range(threads_count)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()
                self.assertEqual(sum(results), limit)
                self.assertEqual(len(results), threads_count)


if __name__ == "__main__":
    unittest.main()
