"""Money as integer minor units, plus the one rounding rule for splitting it.

Floats never touch money. An amount enters as a string or Decimal, is checked
for exact precision, and is stored as an int count of minor units (cents for
USD, yen for JPY). Splitting uses exact fractions and the largest-remainder
rule, so the parts always add back to the total.
"""
import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from .errors import CurrencyMismatchError, InvalidAmountError, InvalidSplitError

CURRENCY_CODE_LENGTH = 3  # ISO 4217 codes are three letters


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO 4217 currency and how many digits follow its decimal point."""

    code: str
    exponent: int

    def __post_init__(self) -> None:
        if len(self.code) != CURRENCY_CODE_LENGTH or not self.code.isalpha() or not self.code.isupper():
            raise InvalidAmountError(f"bad currency code {self.code!r}")
        if self.exponent < 0:
            raise InvalidAmountError(f"exponent must be >= 0, got {self.exponent}")


USD = Currency("USD", 2)
EUR = Currency("EUR", 2)
INR = Currency("INR", 2)
JPY = Currency("JPY", 0)


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount: an int count of minor units in one currency."""

    minor: int
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise InvalidAmountError(f"minor units must be an int, got {self.minor!r}")

    @classmethod
    def of(cls, amount: str | Decimal | int, currency: Currency) -> "Money":
        """Parse a human amount like "12.34". Rejects floats and extra decimal places."""
        if isinstance(amount, float):
            raise InvalidAmountError("pass money as a str or Decimal, never a float")
        try:
            value = Decimal(amount)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise InvalidAmountError(f"not an amount: {amount!r}") from exc
        if not value.is_finite():
            raise InvalidAmountError(f"not a finite amount: {amount!r}")
        scaled = value.scaleb(currency.exponent)
        if scaled != scaled.to_integral_value():
            raise InvalidAmountError(
                f"{amount} has more than {currency.exponent} decimal places for {currency.code}"
            )
        return cls(int(scaled), currency)

    @classmethod
    def zero(cls, currency: Currency) -> "Money":
        return cls(0, currency)

    def _same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"cannot combine {self.currency.code} with {other.currency.code}")

    def __add__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._same_currency(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor, self.currency)

    def is_positive(self) -> bool:
        return self.minor > 0

    def __str__(self) -> str:
        exp = self.currency.exponent
        return f"{self.currency.code} {Decimal(self.minor).scaleb(-exp):.{exp}f}"


def allocate(total_minor: int, weights: Sequence[Fraction]) -> list[int]:
    """Split total_minor in proportion to weights. The parts always sum to total_minor.

    Rounding rule (largest remainder): each part first gets the floor of its
    exact share. The few minor units left over go one each to the parts with
    the largest fractional remainders. Ties go to the earlier position, so the
    caller's participant order decides who absorbs the odd cent.
    """
    if not weights:
        raise InvalidSplitError("nothing to allocate between")
    if any(w < 0 for w in weights):
        raise InvalidSplitError("weights must not be negative")
    weight_sum = sum(weights, Fraction(0))
    if weight_sum == 0:
        raise InvalidSplitError("at least one weight must be positive")
    exact = [Fraction(total_minor) * w / weight_sum for w in weights]
    parts = [math.floor(e) for e in exact]
    leftover = total_minor - sum(parts)
    by_remainder = sorted(range(len(parts)), key=lambda i: (-(exact[i] - parts[i]), i))
    for i in by_remainder[:leftover]:
        parts[i] += 1
    return parts
