"""ExpenseService: the one front door for users, groups, expenses, and settle-ups.

Concurrency: one lock per group. Every read or write of a group's ledger,
membership, or expenses happens under that group's lock, so check-then-act
steps (is this payment an overpayment? then record it) are atomic. The audit
entry is written under the same lock, so the trail's order matches the order
the ledger changed. Different groups never contend. _locks_guard only
protects the lock and ledger maps.
"""

import logging
import threading
from collections.abc import Iterable

from .audit import AuditAction, AuditEntry, AuditLog, InMemoryAuditLog
from .clock import Clock, IdGenerator, SystemClock, UuidIds
from .config import SplitwiseConfig
from .errors import (
    ExpenseAlreadyDeletedError,
    InvalidAmountError,
    InvalidInputError,
    InvalidSettlementError,
    InvalidSplitError,
    NotAGroupMemberError,
    OverpaymentError,
    UnknownGroupError,
    UnsupportedCurrencyError,
)
from .ledger import BalanceLedger
from .models import Debt, Expense, Group, Settlement, User
from .money import Currency, Money
from .repositories import (
    ExpenseRepository,
    GroupRepository,
    InMemoryExpenses,
    InMemoryGroups,
    InMemoryUsers,
    UserRepository,
)
from .simplify import DebtSimplifier, GreedySimplifier
from .splits import SplitStrategy

log = logging.getLogger(__name__)


class ExpenseService:
    def __init__(
        self,
        config: SplitwiseConfig | None = None,
        users: UserRepository | None = None,
        groups: GroupRepository | None = None,
        expenses: ExpenseRepository | None = None,
        audit: AuditLog | None = None,
        simplifier: DebtSimplifier | None = None,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
    ) -> None:
        self._config = config or SplitwiseConfig()
        self._users = users or InMemoryUsers()
        self._groups = groups or InMemoryGroups()
        self._expenses = expenses or InMemoryExpenses()
        self._audit = audit or InMemoryAuditLog()
        self._simplifier = simplifier or GreedySimplifier()
        self._clock = clock or SystemClock()
        self._ids = ids or UuidIds()
        self._locks_guard = threading.Lock()
        self._group_locks: dict[str, threading.Lock] = {}
        self._ledgers: dict[str, BalanceLedger] = {}

    # ----- users and groups -------------------------------------------------

    def register_user(self, user_id: str, name: str) -> User:
        user = User(user_id, name)
        self._users.add(user)
        self._audit.append(self._clock.now(), user_id, AuditAction.USER_REGISTERED, user_id, name)
        log.info("registered user %s", user_id)
        return user

    def create_group(self, name: str, created_by: str, members: Iterable[str] = ()) -> Group:
        member_ids = frozenset(members) | {created_by}
        for user_id in member_ids:
            self._users.get(user_id)  # raises UnknownUserError
        group = Group(self._ids.next_id("grp"), name, member_ids)
        with self._locks_guard:
            self._group_locks[group.group_id] = threading.Lock()
            self._ledgers[group.group_id] = BalanceLedger()
        self._groups.add(group)
        self._audit.append(
            self._clock.now(),
            created_by,
            AuditAction.GROUP_CREATED,
            group.group_id,
            f"{name!r} with {', '.join(sorted(member_ids))}",
        )
        log.info("created group %s", group.group_id)
        return group

    def add_member(self, group_id: str, user_id: str, actor: str) -> Group:
        self._users.get(user_id)
        lock, _ = self._group_state(group_id)
        with lock:
            group = self._groups.get(group_id)
            self._require_members(group, [actor])
            updated = group.with_member(user_id)
            self._groups.update(updated)
            self._audit.append(
                self._clock.now(), actor, AuditAction.MEMBER_ADDED, group_id, user_id
            )
        return updated

    # ----- expenses ---------------------------------------------------------

    def add_expense(
        self, group_id: str, payer_id: str, total: Money, split: SplitStrategy, description: str
    ) -> Expense:
        self._check_description(description)
        self._check_currency(total.currency)
        if len(split.participants) > self._config.max_participants:
            raise InvalidSplitError(
                f"at most {self._config.max_participants} participants per expense"
            )
        shares = split.split(total)  # validates: parts sum to total
        lock, ledger = self._group_state(group_id)
        with lock:
            group = self._groups.get(group_id)
            self._require_members(group, [payer_id, *split.participants])
            expense = Expense(
                self._ids.next_id("exp"),
                group_id,
                description.strip(),
                payer_id,
                total,
                tuple(shares.items()),
                split.kind,
                self._clock.now(),
            )
            self._expenses.add(expense)
            for user_id, share in shares.items():
                ledger.record_debt(user_id, payer_id, share)
            self._audit.append(
                expense.created_at,
                payer_id,
                AuditAction.EXPENSE_ADDED,
                expense.expense_id,
                f"{description.strip()!r} {total} {split.kind} split in {group_id}",
            )
        log.info("expense %s: %s paid %s in %s", expense.expense_id, payer_id, total, group_id)
        return expense

    def delete_expense(self, expense_id: str, actor: str) -> Expense:
        """Reverse an expense's effect on balances. The record stays, flagged deleted."""
        expense = self._expenses.get(expense_id)
        lock, ledger = self._group_state(expense.group_id)
        with lock:
            expense = self._expenses.get(expense_id)  # re-read under the lock
            if expense.deleted:
                raise ExpenseAlreadyDeletedError(expense_id)
            self._require_members(self._groups.get(expense.group_id), [actor])
            for user_id, share in expense.shares:
                ledger.record_debt(expense.payer_id, user_id, share)  # the mirror image
            deleted = Expense(
                expense.expense_id,
                expense.group_id,
                expense.description,
                expense.payer_id,
                expense.total,
                expense.shares,
                expense.split_kind,
                expense.created_at,
                deleted=True,
            )
            self._expenses.update(deleted)
            self._audit.append(
                self._clock.now(),
                actor,
                AuditAction.EXPENSE_DELETED,
                expense_id,
                f"reversed {expense.total} paid by {expense.payer_id}",
            )
        log.info("expense %s deleted by %s", expense_id, actor)
        return deleted

    # ----- settling up ------------------------------------------------------

    def settle_up(self, group_id: str, payer_id: str, payee_id: str, amount: Money) -> Settlement:
        """Record a real payment. It may reduce debt but never create or flip it."""
        if payer_id == payee_id:
            raise InvalidSettlementError("cannot pay yourself")
        if not amount.is_positive():
            raise InvalidAmountError(f"a payment must be positive, got {amount}")
        self._check_currency(amount.currency)
        lock, ledger = self._group_state(group_id)
        with lock:
            self._require_members(self._groups.get(group_id), [payer_id, payee_id])
            net = ledger.net(amount.currency)
            zero = Money.zero(amount.currency)
            payer_owes = -net.get(payer_id, zero).minor
            payee_is_owed = net.get(payee_id, zero).minor
            if amount.minor > payer_owes or amount.minor > payee_is_owed:
                raise OverpaymentError(
                    f"{payer_id} owes {Money(max(payer_owes, 0), amount.currency)} net and "
                    f"{payee_id} is owed {Money(max(payee_is_owed, 0), amount.currency)} net; "
                    f"a payment of {amount} would create new debt"
                )
            settlement = Settlement(
                self._ids.next_id("pay"), group_id, payer_id, payee_id, amount, self._clock.now()
            )
            self._expenses.add_settlement(settlement)
            ledger.record_debt(payee_id, payer_id, amount)  # payee now owes payer back
            self._audit.append(
                settlement.created_at,
                payer_id,
                AuditAction.SETTLEMENT_RECORDED,
                settlement.settlement_id,
                f"{payer_id} paid {payee_id} {amount} in {group_id}",
            )
        log.info(
            "settlement %s: %s paid %s %s", settlement.settlement_id, payer_id, payee_id, amount
        )
        return settlement

    # ----- reading balances -------------------------------------------------

    def net_balances(self, group_id: str, currency: Currency) -> dict[str, Money]:
        lock, ledger = self._group_state(group_id)
        with lock:
            return ledger.net(currency)

    def debts(self, group_id: str, currency: Currency) -> list[Debt]:
        """Pairwise view: who owes whom directly, from the raw expense history."""
        lock, ledger = self._group_state(group_id)
        with lock:
            return ledger.debts(currency)

    def suggest_settlements(self, group_id: str, currency: Currency) -> list[Debt]:
        """Simplified view: a short list of payments that zeroes every net balance."""
        return self._simplifier.simplify(self.net_balances(group_id, currency))

    def open_currencies(self, group_id: str) -> list[Currency]:
        lock, ledger = self._group_state(group_id)
        with lock:
            return ledger.currencies()

    def audit_trail(self, subject_id: str | None = None) -> tuple[AuditEntry, ...]:
        return self._audit.entries(subject_id)

    # ----- helpers ----------------------------------------------------------

    def _group_state(self, group_id: str) -> tuple[threading.Lock, BalanceLedger]:
        with self._locks_guard:
            if group_id not in self._group_locks:
                raise UnknownGroupError(group_id)
            return self._group_locks[group_id], self._ledgers[group_id]

    @staticmethod
    def _require_members(group: Group, user_ids: Iterable[str]) -> None:
        outsiders = sorted(set(user_ids) - group.members)
        if outsiders:
            raise NotAGroupMemberError(f"{', '.join(outsiders)} not in group {group.group_id}")

    def _check_currency(self, currency: Currency) -> None:
        if currency not in self._config.currencies:
            raise UnsupportedCurrencyError(currency.code)

    def _check_description(self, description: str) -> None:
        if not description or not description.strip():
            raise InvalidInputError("description must not be blank")
        if len(description.strip()) > self._config.max_description_length:
            raise InvalidInputError(
                f"description longer than {self._config.max_description_length} chars"
            )
