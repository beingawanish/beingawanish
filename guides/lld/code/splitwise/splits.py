"""Split strategies: how one expense total becomes what each participant owes.

Template method: SplitStrategy.split() asks the subclass for the parts, then
checks the invariant every split must keep. The parts sum to the total,
exactly, in the total's currency. A new split kind is a new subclass; the
invariant check comes free.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import ClassVar

from .errors import InvalidAmountError, InvalidSplitError
from .money import Money, allocate

PERCENT_WHOLE = Fraction(100)  # percentages must add up to exactly this


class SplitStrategy(ABC):
    """Base class. Subclasses compute parts; this class guards the invariant."""

    kind: ClassVar[str]

    @property
    @abstractmethod
    def participants(self) -> tuple[str, ...]:
        """Who shares the expense, in the order used to break rounding ties."""

    @abstractmethod
    def _parts(self, total: Money) -> dict[str, Money]:
        """Each participant's share. May assume total is positive."""

    def split(self, total: Money) -> dict[str, Money]:
        if not total.is_positive():
            raise InvalidAmountError(f"an expense total must be positive, got {total}")
        parts = self._parts(total)
        for user_id, part in parts.items():
            if part.currency != total.currency:
                raise InvalidSplitError(
                    f"{user_id}'s share is in {part.currency.code}, "
                    f"the total is in {total.currency.code}"
                )
            if part.minor < 0:
                raise InvalidSplitError(f"{user_id}'s share is negative: {part}")
        owed = sum(p.minor for p in parts.values())
        if owed != total.minor:
            raise InvalidSplitError(
                f"shares sum to {Money(owed, total.currency)} but the total is {total}"
            )
        return parts


def _unique(ids: Sequence[str]) -> tuple[str, ...]:
    if not ids:
        raise InvalidSplitError("a split needs at least one participant")
    if len(set(ids)) != len(ids):
        raise InvalidSplitError(f"duplicate participants in {list(ids)}")
    return tuple(ids)


class EqualSplit(SplitStrategy):
    """Everyone owes the same; the odd cents go to the earliest-listed participants."""

    kind = "equal"

    def __init__(self, participants: Sequence[str]) -> None:
        self._participants = _unique(participants)

    @property
    def participants(self) -> tuple[str, ...]:
        return self._participants

    def _parts(self, total: Money) -> dict[str, Money]:
        minors = allocate(total.minor, [Fraction(1)] * len(self._participants))
        return {
            u: Money(m, total.currency) for u, m in zip(self._participants, minors, strict=True)
        }


class ExactSplit(SplitStrategy):
    """The caller states each amount. The base class rejects them if they miss the total."""

    kind = "exact"

    def __init__(self, amounts: Mapping[str, Money]) -> None:
        self._participants = _unique(list(amounts))
        self._amounts = dict(amounts)

    @property
    def participants(self) -> tuple[str, ...]:
        return self._participants

    def _parts(self, total: Money) -> dict[str, Money]:
        return dict(self._amounts)


class PercentSplit(SplitStrategy):
    """Each participant owes a percentage. Percentages must add up to exactly 100."""

    kind = "percent"

    def __init__(self, percents: Mapping[str, str | Decimal]) -> None:
        self._participants = _unique(list(percents))
        self._weights: list[Fraction] = []
        for user_id, raw in percents.items():
            if isinstance(raw, float):
                raise InvalidSplitError("pass percentages as str or Decimal, never float")
            try:
                weight = Fraction(Decimal(raw))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise InvalidSplitError(f"{user_id}: not a percentage: {raw!r}") from exc
            if weight < 0:
                raise InvalidSplitError(f"{user_id}: percentage must not be negative")
            self._weights.append(weight)
        if sum(self._weights, Fraction(0)) != PERCENT_WHOLE:
            raise InvalidSplitError(f"percentages sum to {float(sum(self._weights))}, not 100")

    @property
    def participants(self) -> tuple[str, ...]:
        return self._participants

    def _parts(self, total: Money) -> dict[str, Money]:
        minors = allocate(total.minor, self._weights)
        return {
            u: Money(m, total.currency) for u, m in zip(self._participants, minors, strict=True)
        }


class SharesSplit(SplitStrategy):
    """Each participant owes in proportion to a whole number of shares (2 nights vs 3)."""

    kind = "shares"

    def __init__(self, shares: Mapping[str, int]) -> None:
        self._participants = _unique(list(shares))
        for user_id, count in shares.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise InvalidSplitError(f"{user_id}: shares must be a positive int, got {count!r}")
        self._weights = [Fraction(c) for c in shares.values()]

    @property
    def participants(self) -> tuple[str, ...]:
        return self._participants

    def _parts(self, total: Money) -> dict[str, Money]:
        minors = allocate(total.minor, self._weights)
        return {
            u: Money(m, total.currency) for u, m in zip(self._participants, minors, strict=True)
        }
