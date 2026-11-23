"""Money in integer minor units (guide §6.2). Refuses to mix currencies. Pure."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal


class CurrencyMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Money:
    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount_minor, int) or isinstance(self.amount_minor, bool):
            raise TypeError("amount_minor must be an int (never a float)")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(f"currency must be ISO 4217 upper case, got {self.currency!r}")

    @classmethod
    def zero(cls, currency: str) -> Money:
        return cls(0, currency)

    def _check(self, other: Money) -> None:
        if other.currency != self.currency:
            raise CurrencyMismatch(f"cannot combine {self.currency} and {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor + other.amount_minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.amount_minor - other.amount_minor, self.currency)

    def times(self, n: int) -> Money:
        return Money(self.amount_minor * n, self.currency)

    def share(self, rate: Decimal) -> Money:
        """``rate`` of this amount, banker's rounding to the minor unit (tax at line level)."""
        q = (Decimal(self.amount_minor) * rate).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
        return Money(int(q), self.currency)

    def to_dict(self) -> dict[str, object]:
        return {"amountMinor": self.amount_minor, "currency": self.currency}

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> Money:
        return cls(int(d["amountMinor"]), str(d["currency"]))  # type: ignore[call-overload]

    def __str__(self) -> str:
        return f"{self.amount_minor / 100:.2f} {self.currency}"


def total(items: list[Money], currency: str) -> Money:
    acc = Money.zero(currency)
    for m in items:
        acc = acc + m
    return acc
