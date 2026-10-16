"""Configuration: algorithms, key scopes, limit rules, and the tier table.

Every number the limiter enforces lives here. The algorithms read a LimitRule;
they never contain a literal limit or window of their own.
"""
from dataclasses import dataclass, field
from enum import StrEnum

from .errors import ConfigError, InvalidRuleError


class Algorithm(StrEnum):
    """Names of the built-in algorithms. A custom one can use any other string."""

    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"
    FIXED_WINDOW = "fixed_window"
    SLIDING_LOG = "sliding_log"
    SLIDING_COUNTER = "sliding_counter"


# Only bucket algorithms have a capacity separate from their refill rate.
BUCKET_ALGORITHMS: frozenset[str] = frozenset(
    {Algorithm.TOKEN_BUCKET, Algorithm.LEAKY_BUCKET}
)


class KeyScope(StrEnum):
    """What a limit is counted against."""

    USER = "user"
    API_KEY = "api_key"
    IP = "ip"


@dataclass(frozen=True, slots=True)
class LimitRule:
    """`limit` requests per `window_seconds`, enforced by `algorithm`.

    `burst` (bucket algorithms only) sets the bucket size separately from the
    average rate: 100 per minute on average, but up to 300 at once.
    """

    name: str
    limit: int
    window_seconds: float
    algorithm: str = Algorithm.TOKEN_BUCKET
    burst: int | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidRuleError("rule name must not be blank")
        if self.limit < 1:
            raise InvalidRuleError(f"{self.name}: limit must be >= 1, got {self.limit}")
        if self.window_seconds <= 0:
            raise InvalidRuleError(
                f"{self.name}: window_seconds must be > 0, got {self.window_seconds}"
            )
        if self.burst is not None:
            if self.algorithm not in BUCKET_ALGORITHMS:
                raise InvalidRuleError(
                    f"{self.name}: burst only applies to bucket algorithms, "
                    f"not {self.algorithm}"
                )
            if self.burst < 1:
                raise InvalidRuleError(f"{self.name}: burst must be >= 1, got {self.burst}")

    @property
    def capacity(self) -> int:
        """The most requests that can pass at one instant."""
        return self.burst if self.burst is not None else self.limit

    @property
    def rate_per_second(self) -> float:
        """The long-run average rate the rule allows."""
        return self.limit / self.window_seconds


def _default_tiers() -> dict[str, LimitRule]:
    rules = (
        LimitRule("anonymous", 30, 60.0, Algorithm.SLIDING_COUNTER),
        LimitRule("free", 100, 60.0, Algorithm.TOKEN_BUCKET),
        LimitRule("pro", 1_000, 60.0, Algorithm.TOKEN_BUCKET, burst=2_000),
        LimitRule("partner", 100_000, 86_400.0, Algorithm.FIXED_WINDOW),
    )
    return {rule.name: rule for rule in rules}


def _default_scope_tiers() -> dict[KeyScope, str]:
    return {KeyScope.IP: "anonymous", KeyScope.USER: "free", KeyScope.API_KEY: "free"}


@dataclass(frozen=True)
class RateLimiterConfig:
    """The tier table plus the limiter's operational knobs.

    tiers                  -- tier name -> rule; the key must equal rule.name
    default_tier_by_scope  -- tier used when a client key carries no tier
    idle_grace_seconds     -- extra time an idle key is kept past its reset point
    sweep_interval_seconds -- how often the background sweeper purges idle keys
    fail_open              -- on a store failure: allow (True) or refuse (False)
    """

    tiers: dict[str, LimitRule] = field(default_factory=_default_tiers)
    default_tier_by_scope: dict[KeyScope, str] = field(default_factory=_default_scope_tiers)
    idle_grace_seconds: float = 5.0
    sweep_interval_seconds: float = 30.0
    fail_open: bool = True

    def __post_init__(self) -> None:
        if not self.tiers:
            raise ConfigError("at least one tier is required")
        for tier_name, rule in self.tiers.items():
            if tier_name != rule.name:
                raise ConfigError(f"tier key {tier_name!r} does not match rule {rule.name!r}")
        for scope, tier_name in self.default_tier_by_scope.items():
            if tier_name not in self.tiers:
                raise ConfigError(f"scope {scope} defaults to unknown tier {tier_name!r}")
        if self.idle_grace_seconds < 0:
            raise ConfigError("idle_grace_seconds must be >= 0")
        if self.sweep_interval_seconds <= 0:
            raise ConfigError("sweep_interval_seconds must be > 0")
