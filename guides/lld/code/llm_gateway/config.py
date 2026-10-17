"""Configuration: models, prices, routes, team policies and every tunable.

Nothing in the gateway contains a literal price, limit or delay. Routes name
models by key ("provider/model"), and __post_init__ rejects a route that
points at a model nobody configured, so a typo fails at startup, not at 3 a.m.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum


class CostTier(IntEnum):
    ECONOMY = 1
    STANDARD = 2
    PREMIUM = 3


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    tier: CostTier
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.model}"


@dataclass(frozen=True)
class TeamPolicy:
    requests_per_minute: int
    tokens_per_minute: int
    token_budget: int
    max_tier: CostTier = CostTier.PREMIUM

    def __post_init__(self) -> None:
        for name in ("requests_per_minute", "tokens_per_minute", "token_budget"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 0.25
    max_delay_s: float = 4.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if not 0 < self.base_delay_s <= self.max_delay_s:
            raise ValueError("need 0 < base_delay_s <= max_delay_s")


@dataclass(frozen=True)
class BreakerPolicy:
    failure_threshold: int = 3
    cooldown_s: float = 30.0


@dataclass(frozen=True)
class CacheConfig:
    ttl_s: float = 300.0
    max_entries: int = 1024


def _default_models() -> dict[str, ModelSpec]:
    specs = [
        ModelSpec("alpha", "alpha-large", CostTier.PREMIUM, Decimal("15"), Decimal("75")),
        ModelSpec("alpha", "alpha-small", CostTier.ECONOMY, Decimal("0.80"), Decimal("4")),
        ModelSpec("beta", "beta-large", CostTier.PREMIUM, Decimal("10"), Decimal("30")),
        ModelSpec("beta", "beta-medium", CostTier.STANDARD, Decimal("3"), Decimal("15")),
    ]
    return {spec.key: spec for spec in specs}


def _default_routes() -> dict[str, tuple[str, ...]]:
    return {
        "smart": ("alpha/alpha-large", "beta/beta-large", "beta/beta-medium"),
        "fast": ("alpha/alpha-small", "beta/beta-medium"),
    }


def _default_task_routes() -> dict[str, str]:
    return {"code-review": "smart", "summarise": "fast", "classify": "fast"}


def _default_teams() -> dict[str, TeamPolicy]:
    return {
        "search": TeamPolicy(requests_per_minute=60, tokens_per_minute=100_000,
                             token_budget=5_000_000),
        "support": TeamPolicy(requests_per_minute=30, tokens_per_minute=40_000,
                              token_budget=1_000_000, max_tier=CostTier.STANDARD),
    }


@dataclass(frozen=True)
class GatewayConfig:
    models: dict[str, ModelSpec] = field(default_factory=_default_models)
    routes: dict[str, tuple[str, ...]] = field(default_factory=_default_routes)
    task_routes: dict[str, str] = field(default_factory=_default_task_routes)
    teams: dict[str, TeamPolicy] = field(default_factory=_default_teams)
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    breaker: BreakerPolicy = field(default_factory=BreakerPolicy)
    cache: CacheConfig = field(default_factory=CacheConfig)
    provider_timeout_s: float = 30.0
    rate_window_s: float = 60.0
    chars_per_token: int = 4

    def __post_init__(self) -> None:
        for alias, keys in self.routes.items():
            if not keys:
                raise ValueError(f"route {alias!r} has no models")
            for key in keys:
                if key not in self.models:
                    raise ValueError(f"route {alias!r} names unknown model {key!r}")
        for task, alias in self.task_routes.items():
            if alias not in self.routes:
                raise ValueError(f"task {task!r} maps to unknown route {alias!r}")
