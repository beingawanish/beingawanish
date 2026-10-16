"""Expense sharing (Splitwise-style): exact money, pluggable splits, simplified debts."""
from .audit import AuditAction, AuditEntry, AuditLog, InMemoryAuditLog
from .clock import Clock, FixedClock, IdGenerator, SequentialIds, SystemClock, UuidIds
from .config import SplitwiseConfig
from .errors import (
    ConfigError,
    CurrencyMismatchError,
    DuplicateIdError,
    ExpenseAlreadyDeletedError,
    InvalidAmountError,
    InvalidInputError,
    InvalidSettlementError,
    InvalidSplitError,
    LedgerInvariantError,
    NotAGroupMemberError,
    NotFoundError,
    OverpaymentError,
    SplitwiseError,
    UnknownExpenseError,
    UnknownGroupError,
    UnknownUserError,
    UnsupportedCurrencyError,
)
from .ledger import BalanceLedger
from .models import Debt, Expense, Group, Settlement, User
from .money import EUR, INR, JPY, USD, Currency, Money, allocate
from .repositories import (
    ExpenseRepository,
    GroupRepository,
    InMemoryExpenses,
    InMemoryGroups,
    InMemoryUsers,
    UserRepository,
)
from .service import ExpenseService
from .simplify import DebtSimplifier, GreedySimplifier
from .splits import EqualSplit, ExactSplit, PercentSplit, SharesSplit, SplitStrategy

__all__ = [
    "AuditAction", "AuditEntry", "AuditLog", "InMemoryAuditLog",
    "Clock", "FixedClock", "IdGenerator", "SequentialIds", "SystemClock", "UuidIds",
    "SplitwiseConfig",
    "ConfigError", "CurrencyMismatchError", "DuplicateIdError", "ExpenseAlreadyDeletedError",
    "InvalidAmountError", "InvalidInputError", "InvalidSettlementError", "InvalidSplitError",
    "LedgerInvariantError", "NotAGroupMemberError", "NotFoundError", "OverpaymentError",
    "SplitwiseError", "UnknownExpenseError", "UnknownGroupError", "UnknownUserError",
    "UnsupportedCurrencyError",
    "BalanceLedger",
    "Debt", "Expense", "Group", "Settlement", "User",
    "EUR", "INR", "JPY", "USD", "Currency", "Money", "allocate",
    "ExpenseRepository", "GroupRepository", "InMemoryExpenses", "InMemoryGroups",
    "InMemoryUsers", "UserRepository",
    "ExpenseService",
    "DebtSimplifier", "GreedySimplifier",
    "EqualSplit", "ExactSplit", "PercentSplit", "SharesSplit", "SplitStrategy",
]
