"""Domain records: users, groups, expenses, settlements, and debts.

All frozen. A change produces a new record; nothing is edited in place.
"""
from dataclasses import dataclass
from datetime import datetime

from .errors import InvalidInputError, InvalidSplitError
from .money import Money


def _require_text(value: str, what: str) -> None:
    if not value or not value.strip():
        raise InvalidInputError(f"{what} must not be blank")


@dataclass(frozen=True, slots=True)
class User:
    user_id: str
    name: str

    def __post_init__(self) -> None:
        _require_text(self.user_id, "user_id")
        _require_text(self.name, "name")


@dataclass(frozen=True, slots=True)
class Group:
    group_id: str
    name: str
    members: frozenset[str]

    def __post_init__(self) -> None:
        _require_text(self.name, "group name")

    def with_member(self, user_id: str) -> "Group":
        return Group(self.group_id, self.name, self.members | {user_id})


@dataclass(frozen=True, slots=True)
class Expense:
    """One bill: who paid, how much, and what each participant owes for it."""

    expense_id: str
    group_id: str
    description: str
    payer_id: str
    total: Money
    shares: tuple[tuple[str, Money], ...]
    split_kind: str
    created_at: datetime
    deleted: bool = False

    def __post_init__(self) -> None:
        owed = sum(m.minor for _, m in self.shares)
        if owed != self.total.minor:
            raise InvalidSplitError(f"shares sum to {owed}, total is {self.total.minor}")

    def owed_by(self) -> dict[str, Money]:
        return dict(self.shares)


@dataclass(frozen=True, slots=True)
class Settlement:
    """A real payment from payer to payee, recorded to reduce debt."""

    settlement_id: str
    group_id: str
    payer_id: str
    payee_id: str
    amount: Money
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Debt:
    """debtor owes creditor amount. Also used for suggested transfers."""

    debtor: str
    creditor: str
    amount: Money

    def __str__(self) -> str:
        return f"{self.debtor} -> {self.creditor}: {self.amount}"
