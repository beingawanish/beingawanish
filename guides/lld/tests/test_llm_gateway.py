"""Tests for the LLM gateway. FakeClock and FakeProvider throughout: no
network, no real sleeping, every number predictable."""
import random
import threading
import unittest
from decimal import Decimal

from llm_gateway import (
    AllProvidersFailedError,
    BlockedContentGuardrail,
    BreakerPolicy,
    BreakerState,
    BudgetExhaustedError,
    CacheConfig,
    ChatRequest,
    CircuitBreaker,
    CircuitOpenError,
    CostLedger,
    CostTier,
    FakeClock,
    FakeProvider,
    GatewayConfig,
    GuardrailChain,
    GuardrailViolationError,
    InMemoryAuditLog,
    InvalidGatewayRequestError,
    LLMGateway,
    Message,
    NoEligibleModelError,
    PiiRedactionGuardrail,
    ProviderInvalidRequestError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    ProviderServerError,
    QuotaManager,
    RateLimitExceededError,
    ResponseCache,
    Retrier,
    RetryPolicy,
    RouteNotFoundError,
    StopReason,
    TableRouter,
    TeamPolicy,
    UnknownTeamError,
    Usage,
    fingerprint,
)


def ask(text="Hello there", team="search", temperature=0.0, max_tokens=64, **route):
    if not route:
        route = {"model": "smart"}
    return ChatRequest(team=team, messages=(Message("user", text),),
                       max_tokens=max_tokens, temperature=temperature, **route)


class Harness:
    """A gateway wired to two fake providers, a fake clock and a seeded RNG."""

    def __init__(self, config=None, guardrail=None):
        self.clock = FakeClock()
        self.alpha = FakeProvider("alpha", self.clock)
        self.beta = FakeProvider("beta", self.clock)
        self.audit = InMemoryAuditLog()
        self.config = config or GatewayConfig()
        self.gateway = LLMGateway({"alpha": self.alpha, "beta": self.beta},
                                  config=self.config, clock=self.clock,
                                  guardrail=guardrail, audit=self.audit,
                                  rng=random.Random(42))


def overloaded(n):
    return [ProviderOverloadedError("529 overloaded") for _ in range(n)]


class RequestValidationTest(unittest.TestCase):
    def test_blank_message_rejected(self):
        with self.assertRaises(InvalidGatewayRequestError):
            Message("user", "   ")

    def test_exactly_one_of_model_or_task(self):
        with self.assertRaises(InvalidGatewayRequestError):
            ChatRequest("search", (Message("user", "hi"),), model="smart", task="summarise")
        with self.assertRaises(InvalidGatewayRequestError):
            ChatRequest("search", (Message("user", "hi"),))

    def test_last_message_must_be_user(self):
        with self.assertRaises(InvalidGatewayRequestError):
            ChatRequest("search", (Message("user", "hi"), Message("assistant", "yo")),
                        model="smart")

    def test_config_rejects_route_to_unknown_model(self):
        with self.assertRaises(ValueError):
            GatewayConfig(routes={"smart": ("alpha/nope",)})


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.config = GatewayConfig()
        self.router = TableRouter(self.config)
        self.premium = self.config.teams["search"]

    def test_alias_gives_full_chain_in_order(self):
        decision = self.router.route(ask(model="smart"), self.premium)
        self.assertEqual([s.key for s in decision.targets],
                         ["alpha/alpha-large", "beta/beta-large", "beta/beta-medium"])

    def test_task_maps_to_alias(self):
        decision = self.router.route(ask(task="summarise"), self.premium)
        self.assertEqual(decision.alias, "fast")

    def test_cost_tier_filters_chain(self):
        standard = self.config.teams["support"]
        decision = self.router.route(ask(model="smart"), standard)
        self.assertEqual([s.key for s in decision.targets], ["beta/beta-medium"])

    def test_no_model_within_tier(self):
        economy = TeamPolicy(10, 1000, 10_000, max_tier=CostTier.ECONOMY)
        with self.assertRaises(NoEligibleModelError):
            self.router.route(ask(model="smart"), economy)

    def test_unknown_alias_and_task(self):
        with self.assertRaises(RouteNotFoundError):
            self.router.route(ask(model="genius"), self.premium)
        with self.assertRaises(RouteNotFoundError):
            self.router.route(ask(task="poetry"), self.premium)


class RetrierTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.policy = RetryPolicy(max_attempts=3, base_delay_s=0.25, max_delay_s=4.0)
        self.retrier = Retrier(self.policy, self.clock, random.Random(1))

    def flaky(self, errors, result="ok"):
        queue = list(errors)
        calls = []

        def operation():
            calls.append(1)
            if queue:
                raise queue.pop(0)
            return result
        return operation, calls

    def test_retryable_errors_are_retried(self):
        op, calls = self.flaky([ProviderServerError("500"), ProviderRateLimitError("429")])
        self.assertEqual(self.retrier.run(op), "ok")
        self.assertEqual(len(calls), 3)
        self.assertGreater(self.clock.now(), 0)

    def test_non_retryable_fails_fast(self):
        op, calls = self.flaky([ProviderInvalidRequestError("400")])
        with self.assertRaises(ProviderInvalidRequestError):
            self.retrier.run(op)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.clock.now(), 0)

    def test_gives_up_after_max_attempts(self):
        op, calls = self.flaky(overloaded(5))
        with self.assertRaises(ProviderOverloadedError):
            self.retrier.run(op)
        self.assertEqual(len(calls), 3)

    def test_full_jitter_stays_under_capped_exponential(self):
        err = ProviderServerError("500")
        for attempt in range(8):
            ceiling = min(4.0, 0.25 * 2 ** attempt)
            for _ in range(50):
                self.assertTrue(0.0 <= self.retrier.delay_for(attempt, err) <= ceiling)

    def test_retry_after_hint_is_honoured(self):
        op, _ = self.flaky([ProviderRateLimitError("429", retry_after_s=2.0)])
        self.retrier.run(op)
        self.assertEqual(self.clock.now(), 2.0)

    def test_retry_after_beyond_max_wait_gives_up_at_once(self):
        op, calls = self.flaky([ProviderRateLimitError("429", retry_after_s=60.0)])
        with self.assertRaises(ProviderRateLimitError):
            self.retrier.run(op)
        self.assertEqual((len(calls), self.clock.now()), (1, 0))


class CircuitBreakerTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.breaker = CircuitBreaker("alpha/alpha-large",
                                      BreakerPolicy(failure_threshold=2, cooldown_s=30),
                                      self.clock)

    def fail(self, err=None):
        def boom():
            raise err or ProviderServerError("500")
        with self.assertRaises(type(err or ProviderServerError("500"))):
            self.breaker.call(boom)

    def test_opens_after_threshold_and_rejects_without_calling(self):
        self.fail()
        self.fail()
        self.assertIs(self.breaker.state, BreakerState.OPEN)
        called = []
        with self.assertRaises(CircuitOpenError):
            self.breaker.call(lambda: called.append(1))
        self.assertEqual(called, [])

    def test_half_open_trial_success_closes(self):
        self.fail()
        self.fail()
        self.clock.advance(30)
        self.assertIs(self.breaker.state, BreakerState.HALF_OPEN)
        self.assertEqual(self.breaker.call(lambda: "ok"), "ok")
        self.assertIs(self.breaker.state, BreakerState.CLOSED)

    def test_half_open_trial_failure_reopens(self):
        self.fail()
        self.fail()
        self.clock.advance(30)
        self.fail()
        self.assertIs(self.breaker.state, BreakerState.OPEN)

    def test_client_errors_do_not_trip_the_breaker(self):
        for _ in range(5):
            self.fail(ProviderInvalidRequestError("400"))
        self.assertIs(self.breaker.state, BreakerState.CLOSED)


class QuotaTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        policy = TeamPolicy(requests_per_minute=2, tokens_per_minute=1000, token_budget=1500)
        self.quotas = QuotaManager({"t": policy}, self.clock, window_s=60)

    def test_requests_per_minute_with_retry_after(self):
        self.quotas.reserve("t", 10)
        self.clock.advance(15)
        self.quotas.reserve("t", 10)
        with self.assertRaises(RateLimitExceededError) as ctx:
            self.quotas.reserve("t", 10)
        self.assertEqual(ctx.exception.retry_after_s, 45)

    def test_tokens_per_minute(self):
        self.quotas.reserve("t", 900)
        with self.assertRaises(RateLimitExceededError):
            self.quotas.reserve("t", 200)

    def test_window_slides(self):
        self.quotas.reserve("t", 900)
        self.clock.advance(60)
        self.quotas.reserve("t", 500)

    def test_settle_and_release_correct_the_estimate(self):
        first = self.quotas.reserve("t", 800)
        self.quotas.settle(first, 100)
        second = self.quotas.reserve("t", 800)  # fits only because of the settle
        self.quotas.release(second)
        self.assertEqual(self.quotas.budget_remaining("t"), 1400)

    def test_budget_exhausted(self):
        self.quotas.reserve("t", 900)
        self.clock.advance(60)
        with self.assertRaises(BudgetExhaustedError):
            self.quotas.reserve("t", 700)

    def test_unknown_team(self):
        with self.assertRaises(UnknownTeamError):
            self.quotas.reserve("ghost", 1)


class LedgerTest(unittest.TestCase):
    def test_price_is_exact_decimal(self):
        ledger = CostLedger(GatewayConfig().models, FakeClock())
        cost = ledger.price("alpha/alpha-large", Usage(1000, 500))
        self.assertEqual(cost, Decimal("0.052500"))  # 1000*15/1M + 500*75/1M

    def test_totals_per_team(self):
        ledger = CostLedger(GatewayConfig().models, FakeClock())
        ledger.record("r1", "a", "beta/beta-medium", Usage(100, 100))
        ledger.record("r2", "a", "beta/beta-medium", Usage(100, 100))
        ledger.record("r3", "b", "beta/beta-medium", Usage(100, 100))
        self.assertEqual(ledger.total_tokens("a"), 400)
        self.assertEqual(ledger.total_cost("a"), Decimal("0.003600"))


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.cache = ResponseCache(CacheConfig(ttl_s=10, max_entries=2), self.clock)

    def test_whitespace_is_normalised_but_case_is_not(self):
        base = fingerprint(ask("Hello there"), "smart")
        self.assertEqual(base, fingerprint(ask("  Hello   there "), "smart"))
        self.assertNotEqual(base, fingerprint(ask("hello there"), "smart"))

    def test_team_is_part_of_the_key(self):
        self.assertNotEqual(fingerprint(ask(team="a"), "smart"),
                            fingerprint(ask(team="b"), "smart"))

    def test_only_temperature_zero_is_cacheable(self):
        self.assertTrue(ResponseCache.cacheable(ask(temperature=0.0)))
        self.assertFalse(ResponseCache.cacheable(ask(temperature=0.7)))

    def test_ttl_and_lru_eviction(self):
        self.cache.put("a", "A")
        self.clock.advance(10)
        self.assertIsNone(self.cache.get("a"))
        self.cache.put("b", "B")
        self.cache.put("c", "C")
        self.cache.get("b")          # b is now most recent
        self.cache.put("d", "D")     # evicts c
        self.assertEqual((self.cache.get("b"), self.cache.get("c")), ("B", None))


class GuardrailTest(unittest.TestCase):
    def test_pii_is_redacted(self):
        text = "Mail jo.k@example.co.uk, card 4111 1111 1111 1111, call +44 20 7946 0958"
        self.assertEqual(PiiRedactionGuardrail().redact(text),
                         "Mail [EMAIL], card [CARD], call [PHONE]")

    def test_blocked_term_stops_request_and_response(self):
        guard = BlockedContentGuardrail(["drop table"])
        with self.assertRaises(GuardrailViolationError):
            guard.check_request(ask("please DROP TABLE users"))
        with self.assertRaises(GuardrailViolationError):
            guard.check_response("sure: drop table users;")

    def test_chain_runs_in_order(self):
        # Redaction first means the blocker never sees the raw address.
        chain = GuardrailChain([PiiRedactionGuardrail(),
                                BlockedContentGuardrail(["ceo@corp.com"])])
        cleaned = chain.check_request(ask("forward to ceo@corp.com"))
        self.assertEqual(cleaned.messages[0].content, "forward to [EMAIL]")


class GatewayTest(unittest.TestCase):
    def test_happy_path_usage_and_cost(self):
        h = Harness()
        r = h.gateway.complete(ask("Hello there"))
        self.assertEqual((r.provider, r.model), ("alpha", "alpha-large"))
        self.assertEqual(r.usage, Usage(input_tokens=3, output_tokens=8))
        self.assertEqual(r.cost_usd, Decimal("0.000645"))  # 3*15 + 8*75, per million
        self.assertEqual(r.stop_reason, StopReason.END_TURN)
        self.assertEqual(h.gateway.ledger.total_cost("search"), r.cost_usd)

    def test_max_tokens_stop_reason(self):
        r = Harness().gateway.complete(ask("Hello there", max_tokens=2))
        self.assertEqual((r.stop_reason, r.usage.output_tokens), (StopReason.MAX_TOKENS, 2))

    def test_falls_back_when_primary_keeps_failing(self):
        h = Harness()
        h.alpha.fail_next(*overloaded(3))
        r = h.gateway.complete(ask())
        self.assertEqual(r.model, "beta-large")
        self.assertEqual(r.fallbacks, ("alpha/alpha-large",))
        self.assertEqual(len(h.alpha.calls), 3)  # retried before falling back

    def test_timeout_triggers_fallback(self):
        h = Harness()
        h.alpha.set_latency(31.0)  # default timeout is 30s
        r = h.gateway.complete(ask())
        self.assertEqual(r.provider, "beta")

    def test_client_error_does_not_fall_back(self):
        h = Harness()
        h.alpha.fail_next(ProviderInvalidRequestError("400 bad request"))
        with self.assertRaises(ProviderInvalidRequestError):
            h.gateway.complete(ask())
        self.assertEqual(h.beta.calls, [])

    def test_all_providers_failing_releases_the_quota(self):
        h = Harness()
        h.alpha.fail_next(*overloaded(3))
        h.beta.fail_next(*overloaded(6))
        before = h.gateway.quotas.budget_remaining("search")
        with self.assertRaises(AllProvidersFailedError) as ctx:
            h.gateway.complete(ask())
        self.assertEqual(len(ctx.exception.failures), 3)
        self.assertEqual(h.gateway.quotas.budget_remaining("search"), before)
        self.assertEqual(h.gateway.ledger.entries(), [])

    def test_open_circuit_skips_provider_without_calling_it(self):
        h = Harness()
        h.alpha.fail_next(*overloaded(3))
        h.gateway.complete(ask("first"))
        self.assertIs(h.gateway.breaker("alpha/alpha-large").state, BreakerState.OPEN)
        h.gateway.complete(ask("second"))
        self.assertEqual(len(h.alpha.calls), 3)  # no fourth call

    def test_cache_hit_costs_nothing_and_skips_providers(self):
        h = Harness()
        h.gateway.complete(ask("Hello there"))
        r = h.gateway.complete(ask("Hello   there"))
        self.assertTrue(r.cached)
        self.assertEqual(r.cost_usd, Decimal("0"))
        self.assertEqual(len(h.alpha.calls), 1)
        self.assertEqual(len(h.gateway.ledger.entries()), 1)

    def test_rate_limit_rejects_before_any_provider_call(self):
        config = GatewayConfig(teams={"search": TeamPolicy(1, 10_000, 100_000)})
        h = Harness(config)
        h.gateway.complete(ask("one"))
        with self.assertRaises(RateLimitExceededError):
            h.gateway.complete(ask("two"))
        self.assertEqual(len(h.alpha.calls), 1)

    def test_blocked_response_is_still_billed(self):
        h = Harness(guardrail=BlockedContentGuardrail(["alpha-large says"]))
        with self.assertRaises(GuardrailViolationError):
            h.gateway.complete(ask())
        self.assertEqual(len(h.gateway.ledger.entries()), 1)
        self.assertEqual(h.audit.records()[-1].outcome, "blocked_response")

    def test_audit_never_contains_the_prompt(self):
        h = Harness()
        secret = "Project Nightjar launches Friday"
        with self.assertLogs("llm_gateway", level="INFO") as logs:
            h.gateway.complete(ask(secret))
        record = h.audit.records()[0]
        self.assertEqual((record.outcome, record.prompt_chars), ("ok", len(secret) + 1))
        self.assertEqual(len(record.prompt_fingerprint), 64)
        self.assertNotIn("Nightjar", repr(record))
        self.assertFalse(any("Nightjar" in line for line in logs.output))

    def test_concurrent_requests_respect_requests_per_minute(self):
        config = GatewayConfig(teams={"search": TeamPolicy(5, 1_000_000, 10_000_000)})
        h = Harness(config)
        barrier = threading.Barrier(20)
        outcomes = []
        lock = threading.Lock()

        def worker(i):
            barrier.wait()
            try:
                h.gateway.complete(ask(f"request {i}"))
                result = "ok"
            except RateLimitExceededError:
                result = "limited"
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual((outcomes.count("ok"), outcomes.count("limited")), (5, 15))


if __name__ == "__main__":
    unittest.main()
