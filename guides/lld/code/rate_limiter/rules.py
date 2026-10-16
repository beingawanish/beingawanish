"""Who is asking, and which rule applies to them.

ClientKey names the thing being limited (a user, an API key, an IP).
RuleBook turns a ClientKey into a LimitRule using the tier table.
"""
from dataclasses import dataclass

from .config import KeyScope, LimitRule, RateLimiterConfig
from .errors import InvalidKeyError, UnknownTierError


@dataclass(frozen=True, slots=True)
class ClientKey:
    """One limited identity. `tier` overrides the scope's default tier."""

    scope: KeyScope
    value: str
    tier: str | None = None

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise InvalidKeyError(f"{self.scope} key must not be blank")

    def storage_key(self, rule: LimitRule) -> str:
        """The store key. Rule and algorithm are part of it, so a plan change
        starts a fresh counter and two algorithms never read each other's state."""
        return f"rl:{rule.name}:{rule.algorithm}:{self.scope}:{self.value}"


class RuleBook:
    """Resolves the rule for a client: explicit tier first, then the scope default."""

    def __init__(self, config: RateLimiterConfig) -> None:
        self._config = config

    def rule_for(self, client: ClientKey) -> LimitRule:
        tier = client.tier or self._config.default_tier_by_scope.get(client.scope)
        if tier is None:
            raise UnknownTierError(f"no tier given and no default for scope {client.scope}")
        rule = self._config.tiers.get(tier)
        if rule is None:
            raise UnknownTierError(f"unknown tier {tier!r}")
        return rule

    def rules(self) -> list[LimitRule]:
        return list(self._config.tiers.values())
