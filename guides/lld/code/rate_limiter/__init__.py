"""Rate limiter: pluggable algorithms, per-key tiers, a storage seam."""
from .algorithms import (
    FixedWindow,
    LeakyBucket,
    RateLimitAlgorithm,
    SlidingWindowCounter,
    SlidingWindowLog,
    TokenBucket,
    default_algorithms,
)
from .clock import Clock, ManualClock, MonotonicClock
from .config import Algorithm, KeyScope, LimitRule, RateLimiterConfig
from .decision import Decision
from .errors import (
    ConfigError,
    InvalidCostError,
    InvalidKeyError,
    InvalidRequestError,
    InvalidRuleError,
    LimiterUnavailableError,
    RateLimiterError,
    StoreError,
    UnknownAlgorithmError,
    UnknownTierError,
)
from .limiter import IdleKeySweeper, RateLimiter
from .rules import ClientKey, RuleBook
from .store import InMemoryStore, StateStore

__all__ = [
    "Algorithm", "ClientKey", "Clock", "ConfigError", "Decision", "FixedWindow",
    "IdleKeySweeper", "InMemoryStore", "InvalidCostError", "InvalidKeyError",
    "InvalidRequestError", "InvalidRuleError", "KeyScope", "LeakyBucket",
    "LimitRule", "LimiterUnavailableError", "ManualClock", "MonotonicClock",
    "RateLimitAlgorithm", "RateLimiter", "RateLimiterConfig", "RateLimiterError",
    "RuleBook", "SlidingWindowCounter", "SlidingWindowLog", "StateStore",
    "StoreError", "TokenBucket", "UnknownAlgorithmError", "UnknownTierError",
    "default_algorithms",
]
