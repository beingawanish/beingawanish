"""The rate limiter's failure modes, one type per recovery path.

A denied request is NOT an error: it is a normal Decision with allowed=False.
Exceptions are reserved for bad configuration, bad input, and a broken store.
"""


class RateLimiterError(Exception):
    """Root of every rate-limiter failure. Catch this to catch them all."""


class ConfigError(RateLimiterError):
    """The limiter was wired with configuration that can never work."""


class InvalidRuleError(ConfigError):
    """A LimitRule has a non-positive limit, window, or a misplaced burst."""


class UnknownAlgorithmError(ConfigError):
    """A rule names an algorithm nobody registered."""


class InvalidRequestError(RateLimiterError):
    """The caller passed input the limiter refuses to evaluate."""


class InvalidKeyError(InvalidRequestError):
    """The client key is blank."""


class InvalidCostError(InvalidRequestError):
    """The request cost is below 1 or larger than the bucket could ever hold."""


class UnknownTierError(InvalidRequestError):
    """The client asked for a tier, or has a scope, with no configured rule."""


class StoreError(RateLimiterError):
    """The state store failed (in a distributed setup: Redis timed out)."""


class LimiterUnavailableError(RateLimiterError):
    """The store failed and the limiter is configured to fail closed."""
