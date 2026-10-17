"""The balance ledger: who owes whom, per pair of users, per currency.

One signed int per (currency, pair). The pair key is sorted, so A-owes-B and
B-owes-A are the same row with opposite signs; they cancel automatically.

Not thread-safe on its own. ExpenseService holds the group's lock around
every call, because its check-then-act steps span several ledger calls.
"""

from collections import defaultdict

from .errors import LedgerInvariantError
from .models import Debt
from .money import Currency, Money


class BalanceLedger:
    """Pairwise balances for one group."""

    def __init__(self) -> None:
        # (currency code, low id, high id) -> minor units. Positive: low owes high.
        self._pairs: dict[tuple[str, str, str], int] = defaultdict(int)
        self._currencies: dict[str, Currency] = {}

    def record_debt(self, debtor: str, creditor: str, amount: Money) -> None:
        """debtor now owes creditor `amount` more. Owing yourself is a no-op."""
        if debtor == creditor or amount.minor == 0:
            return
        self._currencies[amount.currency.code] = amount.currency
        low, high = sorted((debtor, creditor))
        sign = 1 if debtor == low else -1
        key = (amount.currency.code, low, high)
        self._pairs[key] += sign * amount.minor
        if self._pairs[key] == 0:
            del self._pairs[key]

    def owed(self, debtor: str, creditor: str, currency: Currency) -> Money:
        """How much debtor owes creditor directly (zero if it runs the other way)."""
        low, high = sorted((debtor, creditor))
        raw = self._pairs.get((currency.code, low, high), 0)
        signed = raw if debtor == low else -raw
        return Money(max(signed, 0), currency)

    def debts(self, currency: Currency) -> list[Debt]:
        """Every nonzero pairwise balance in this currency, sorted for stable output."""
        out = []
        for (code, low, high), raw in sorted(self._pairs.items()):
            if code != currency.code:
                continue
            if raw > 0:
                out.append(Debt(low, high, Money(raw, currency)))
            else:
                out.append(Debt(high, low, Money(-raw, currency)))
        return out

    def net(self, currency: Currency) -> dict[str, Money]:
        """Per-user net position. Positive: the group owes them. Always sums to zero."""
        totals: dict[str, int] = defaultdict(int)
        for (code, low, high), raw in self._pairs.items():
            if code == currency.code:
                totals[low] -= raw
                totals[high] += raw
        if sum(totals.values()) != 0:
            raise LedgerInvariantError(f"{currency.code} nets sum to {sum(totals.values())}")
        return {u: Money(v, currency) for u, v in sorted(totals.items()) if v != 0}

    def currencies(self) -> list[Currency]:
        """Currencies with at least one open balance."""
        open_codes = {code for code, _, _ in self._pairs}
        return [c for code, c in sorted(self._currencies.items()) if code in open_codes]
