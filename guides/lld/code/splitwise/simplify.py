"""Debt simplification: turn net balances into a short list of payments.

The minimum number of payments is NP-hard to find in general. It needs the
largest number of disjoint zero-sum subgroups, which is a partition-style
problem. GreedySimplifier is the practical answer: at most n - 1 payments,
O(n log n), and nobody pays more than they owe or receives more than they are
owed. It is not always minimal; the tests pin a case where it is not.
"""

import heapq
from abc import ABC, abstractmethod
from collections.abc import Mapping

from .errors import CurrencyMismatchError, LedgerInvariantError
from .models import Debt
from .money import Money


class DebtSimplifier(ABC):
    @abstractmethod
    def simplify(self, net: Mapping[str, Money]) -> list[Debt]:
        """Payments that bring every net balance to zero. Positive net: is owed."""


class GreedySimplifier(DebtSimplifier):
    """Largest debtor pays largest creditor the smaller of the two amounts. Repeat."""

    def simplify(self, net: Mapping[str, Money]) -> list[Debt]:
        if not net:
            return []
        currency = next(iter(net.values())).currency
        if any(m.currency != currency for m in net.values()):
            raise CurrencyMismatchError("simplify one currency at a time")
        if sum(m.minor for m in net.values()) != 0:
            raise LedgerInvariantError("net balances must sum to zero")
        # heapq is a min-heap, so store negated amounts to pop the largest first.
        # The user id breaks ties, which keeps the output deterministic.
        creditors = [(-m.minor, u) for u, m in net.items() if m.minor > 0]
        debtors = [(m.minor, u) for u, m in net.items() if m.minor < 0]
        heapq.heapify(creditors)
        heapq.heapify(debtors)
        payments: list[Debt] = []
        while creditors and debtors:
            credit, creditor = heapq.heappop(creditors)
            debit, debtor = heapq.heappop(debtors)
            credit, debit = -credit, -debit
            paid = min(credit, debit)
            payments.append(Debt(debtor, creditor, Money(paid, currency)))
            if credit > paid:
                heapq.heappush(creditors, (-(credit - paid), creditor))
            if debit > paid:
                heapq.heappush(debtors, (-(debit - paid), debtor))
        return payments
