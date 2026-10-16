"""The gateway: one front door that every team calls instead of a provider.

complete() runs the pipeline in a fixed order:

  guardrails in -> route -> cache -> quota -> fallback chain
  (each model: breaker + retries) -> settle quota -> ledger
  -> guardrails out -> cache store -> audit

The gateway orchestrates; each step's logic lives in its own collaborator.
Shared state lives only inside those collaborators, each behind its own lock,
so complete() is safe to call from many threads at once.
"""
import logging
import math
import random
import uuid
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal

from .audit import AuditLog, AuditRecord, InMemoryAuditLog
from .cache import ResponseCache, fingerprint
from .clock import Clock, SystemClock
from .config import GatewayConfig, ModelSpec
from .errors import (
    AllProvidersFailedError,
    CircuitOpenError,
    GatewayError,
    GuardrailViolationError,
    ProviderError,
)
from .guardrails import Guardrail, GuardrailChain
from .ledger import CostLedger
from .models import ChatRequest, ChatResponse, ProviderResult
from .providers import ModelProvider
from .quotas import QuotaManager
from .resilience import CircuitBreaker, Retrier
from .routing import RouteDecision, RoutingStrategy, TableRouter

log = logging.getLogger(__name__)


def _new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class LLMGateway:
    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        config: GatewayConfig | None = None,
        clock: Clock | None = None,
        router: RoutingStrategy | None = None,
        guardrail: Guardrail | None = None,
        audit: AuditLog | None = None,
        rng: random.Random | None = None,
        id_factory: Callable[[], str] = _new_request_id,
    ) -> None:
        self._config = config or GatewayConfig()
        missing = {s.provider for s in self._config.models.values()} - set(providers)
        if missing:
            raise ValueError(f"no provider registered for {sorted(missing)}")
        self._providers = dict(providers)
        self._clock = clock or SystemClock()
        self._router = router or TableRouter(self._config)
        self._guardrail = guardrail or GuardrailChain()
        self._audit = audit or InMemoryAuditLog()
        self._new_id = id_factory
        self._quotas = QuotaManager(self._config.teams, self._clock, self._config.rate_window_s)
        self._ledger = CostLedger(self._config.models, self._clock)
        self._cache = ResponseCache(self._config.cache, self._clock)
        self._retrier = Retrier(self._config.retry, self._clock, rng or random.Random())
        self._breakers = {key: CircuitBreaker(key, self._config.breaker, self._clock)
                          for key in self._config.models}

    @property
    def ledger(self) -> CostLedger:
        return self._ledger

    @property
    def quotas(self) -> QuotaManager:
        return self._quotas

    def breaker(self, model_key: str) -> CircuitBreaker:
        return self._breakers[model_key]

    # -- the pipeline -----------------------------------------------------

    def complete(self, request: ChatRequest) -> ChatResponse:
        started = self._clock.now()
        policy = self._quotas.policy(request.team)
        audit = AuditRecord(self._new_id(), request.team, route="", outcome="",
                            prompt_chars=len(request.prompt_text()))
        try:
            request = self._guardrail.check_request(request)
        except GuardrailViolationError as err:
            self._finish(audit, started, outcome="blocked_request", error=str(err))
            raise
        decision = self._router.route(request, policy)
        key = fingerprint(request, decision.alias)
        audit = replace(audit, route=decision.alias, prompt_fingerprint=key)

        if self._cache.cacheable(request):
            hit = self._cache.get(key)
            if hit is not None:
                self._finish(audit, started, outcome="cache_hit", cached=True,
                             model_key=f"{hit.provider}/{hit.model}")
                return replace(hit, request_id=audit.request_id, cost_usd=Decimal("0"),
                               cached=True, fallbacks=())

        reservation = self._quotas.reserve(request.team, self._estimate(request))
        try:
            spec, result, failed = self._run_chain(request, decision)
        except GatewayError as err:
            self._quotas.release(reservation)
            self._finish(audit, started, outcome="error", error=type(err).__name__)
            raise
        self._quotas.settle(reservation, result.usage.total)
        entry = self._ledger.record(audit.request_id, request.team, spec.key, result.usage)
        audit = replace(audit, model_key=spec.key, input_tokens=result.usage.input_tokens,
                        output_tokens=result.usage.output_tokens, cost_usd=entry.cost_usd,
                        fallbacks=len(failed))
        try:
            text = self._guardrail.check_response(result.text)
        except GuardrailViolationError as err:
            self._finish(audit, started, outcome="blocked_response", error=str(err))
            raise
        response = ChatResponse(audit.request_id, text, spec.provider, spec.model,
                                result.usage, result.stop_reason, entry.cost_usd,
                                fallbacks=failed)
        if self._cache.cacheable(request):
            self._cache.put(key, response)
        self._finish(audit, started, outcome="ok")
        return response

    # -- helpers ----------------------------------------------------------

    def _estimate(self, request: ChatRequest) -> int:
        """Worst case: every prompt token plus the full max_tokens of output."""
        prompt = math.ceil(len(request.prompt_text()) / self._config.chars_per_token)
        return prompt + request.max_tokens

    def _run_chain(self, request: ChatRequest, decision: RouteDecision
                   ) -> tuple[ModelSpec, ProviderResult, tuple[str, ...]]:
        failures: list[tuple[str, Exception]] = []
        for spec in decision.targets:
            try:
                result = self._call_model(spec, request)
            except CircuitOpenError as err:
                failures.append((spec.key, err))
                continue
            except ProviderError as err:
                if not err.retryable:
                    raise
                log.warning("%s failed (%s); falling back", spec.key, type(err).__name__)
                failures.append((spec.key, err))
                continue
            return spec, result, tuple(key for key, _ in failures)
        raise AllProvidersFailedError(decision.alias, failures)

    def _call_model(self, spec: ModelSpec, request: ChatRequest) -> ProviderResult:
        provider = self._providers[spec.provider]
        breaker = self._breakers[spec.key]
        timeout = self._config.provider_timeout_s
        return self._retrier.run(
            lambda: breaker.call(lambda: provider.complete(spec.model, request, timeout)))

    def _finish(self, audit: AuditRecord, started: float, **changes: object) -> None:
        latency = self._clock.now() - started
        self._audit.write(replace(audit, latency_s=latency, **changes))
