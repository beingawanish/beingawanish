"""Configuration: every limit and the supported currencies, in one frozen dataclass."""
from dataclasses import dataclass

from .errors import ConfigError
from .money import EUR, INR, JPY, USD, Currency


@dataclass(frozen=True, slots=True)
class SplitwiseConfig:
    """Tunables for the expense service. Validated once, at construction."""

    currencies: tuple[Currency, ...] = (USD, EUR, INR, JPY)
    max_participants: int = 50
    max_description_length: int = 120

    def __post_init__(self) -> None:
        if not self.currencies:
            raise ConfigError("at least one currency is required")
        codes = [c.code for c in self.currencies]
        if len(set(codes)) != len(codes):
            raise ConfigError(f"duplicate currency codes in {codes}")
        if self.max_participants < 1:
            raise ConfigError("max_participants must be >= 1")
        if self.max_description_length < 1:
            raise ConfigError("max_description_length must be >= 1")
