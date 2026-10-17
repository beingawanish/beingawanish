"""Repositories: storage behind interfaces. In-memory today, a database later.

Each in-memory repository has its own lock guarding its own dict.
"""

import threading
from abc import ABC, abstractmethod

from .errors import DuplicateIdError, UnknownExpenseError, UnknownGroupError, UnknownUserError
from .models import Expense, Group, Settlement, User


class UserRepository(ABC):
    @abstractmethod
    def add(self, user: User) -> None: ...

    @abstractmethod
    def get(self, user_id: str) -> User: ...


class GroupRepository(ABC):
    @abstractmethod
    def add(self, group: Group) -> None: ...

    @abstractmethod
    def get(self, group_id: str) -> Group: ...

    @abstractmethod
    def update(self, group: Group) -> None: ...


class ExpenseRepository(ABC):
    @abstractmethod
    def add(self, expense: Expense) -> None: ...

    @abstractmethod
    def get(self, expense_id: str) -> Expense: ...

    @abstractmethod
    def update(self, expense: Expense) -> None: ...

    @abstractmethod
    def for_group(self, group_id: str) -> list[Expense]: ...

    @abstractmethod
    def add_settlement(self, settlement: Settlement) -> None: ...

    @abstractmethod
    def settlements_for_group(self, group_id: str) -> list[Settlement]: ...


class InMemoryUsers(UserRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[str, User] = {}

    def add(self, user: User) -> None:
        with self._lock:
            if user.user_id in self._users:
                raise DuplicateIdError(f"user {user.user_id} already exists")
            self._users[user.user_id] = user

    def get(self, user_id: str) -> User:
        with self._lock:
            try:
                return self._users[user_id]
            except KeyError:
                raise UnknownUserError(user_id) from None


class InMemoryGroups(GroupRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._groups: dict[str, Group] = {}

    def add(self, group: Group) -> None:
        with self._lock:
            if group.group_id in self._groups:
                raise DuplicateIdError(f"group {group.group_id} already exists")
            self._groups[group.group_id] = group

    def get(self, group_id: str) -> Group:
        with self._lock:
            try:
                return self._groups[group_id]
            except KeyError:
                raise UnknownGroupError(group_id) from None

    def update(self, group: Group) -> None:
        with self._lock:
            if group.group_id not in self._groups:
                raise UnknownGroupError(group.group_id)
            self._groups[group.group_id] = group


class InMemoryExpenses(ExpenseRepository):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expenses: dict[str, Expense] = {}
        self._settlements: list[Settlement] = []

    def add(self, expense: Expense) -> None:
        with self._lock:
            if expense.expense_id in self._expenses:
                raise DuplicateIdError(f"expense {expense.expense_id} already exists")
            self._expenses[expense.expense_id] = expense

    def get(self, expense_id: str) -> Expense:
        with self._lock:
            try:
                return self._expenses[expense_id]
            except KeyError:
                raise UnknownExpenseError(expense_id) from None

    def update(self, expense: Expense) -> None:
        with self._lock:
            if expense.expense_id not in self._expenses:
                raise UnknownExpenseError(expense.expense_id)
            self._expenses[expense.expense_id] = expense

    def for_group(self, group_id: str) -> list[Expense]:
        with self._lock:
            return [e for e in self._expenses.values() if e.group_id == group_id]

    def add_settlement(self, settlement: Settlement) -> None:
        with self._lock:
            self._settlements.append(settlement)

    def settlements_for_group(self, group_id: str) -> list[Settlement]:
        with self._lock:
            return [s for s in self._settlements if s.group_id == group_id]
