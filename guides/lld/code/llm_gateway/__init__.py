"""LLM gateway: one front door between internal teams and model providers."""
import logging

from .audit import AuditLog, AuditRecord, InMemoryAuditLog
from .cache import ResponseCache, fingerprint
from .clock import Clock, FakeClock, SystemClock
from .config import (
    BreakerPolicy,
    CacheConfig,
    CostTier,
    GatewayConfig,
    ModelSpec,
    RetryPolicy,
    TeamPolicy,
)
from .errors import (
    AllProvidersFailedError,
    BudgetExhaustedError,
    CircuitOpenError,
    GatewayError,
    GuardrailViolationError,
    InvalidGatewayRequestError,
    NoEligibleModelError,
    ProviderError,
    ProviderInvalidRequestError,
    ProviderOverloadedError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderTimeoutError,
    QuotaError,
    RateLimitExceededError,
    RouteNotFoundError,
    UnknownTeamError,
)
from .gateway import LLMGateway
from .guardrails import (
    BlockedContentGuardrail,
    Guardrail,
    GuardrailChain,
    PiiRedactionGuardrail,
)
from .ledger import CostLedger, LedgerEntry
from .models import ChatRequest, ChatResponse, Message, ProviderResult, StopReason, Usage
from .providers import FakeProvider, ModelProvider
from .quotas import QuotaManager, QuotaReservation
from .resilience import BreakerState, CircuitBreaker, Retrier
from .routing import RouteDecision, RoutingStrategy, TableRouter

# A library stays silent until the application configures logging.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "LLMGateway", "GatewayConfig", "ModelSpec", "TeamPolicy", "CostTier",
    "RetryPolicy", "BreakerPolicy", "CacheConfig",
    "Clock", "SystemClock", "FakeClock",
    "ChatRequest", "ChatResponse", "Message", "ProviderResult", "StopReason", "Usage",
    "ModelProvider", "FakeProvider",
    "RoutingStrategy", "TableRouter", "RouteDecision",
    "Retrier", "CircuitBreaker", "BreakerState",
    "QuotaManager", "QuotaReservation", "CostLedger", "LedgerEntry",
    "ResponseCache", "fingerprint",
    "Guardrail", "GuardrailChain", "PiiRedactionGuardrail", "BlockedContentGuardrail",
    "AuditLog", "AuditRecord", "InMemoryAuditLog",
    "GatewayError", "InvalidGatewayRequestError", "UnknownTeamError",
    "RouteNotFoundError", "NoEligibleModelError", "GuardrailViolationError",
    "QuotaError", "RateLimitExceededError", "BudgetExhaustedError",
    "CircuitOpenError", "AllProvidersFailedError",
    "ProviderError", "ProviderRateLimitError", "ProviderOverloadedError",
    "ProviderServerError", "ProviderTimeoutError", "ProviderInvalidRequestError",
]
