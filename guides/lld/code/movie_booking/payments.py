"""Payment gateway seam, plus an in-memory fake with real idempotency semantics.

Idempotency contract (the same one real gateways publish): a charge with a
key the gateway has already seen returns the original receipt and moves no
money. Same key with a different amount is a client bug and is rejected.
"""
import itertools
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from .errors import IdempotencyConflictError, PaymentDeclinedError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentReceipt:
    payment_id: str
    idempotency_key: str
    amount: Decimal


@dataclass(frozen=True)
class RefundReceipt:
    refund_id: str
    payment_id: str
    amount: Decimal


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, *, idempotency_key: str, user_id: str, amount: Decimal) -> PaymentReceipt:
        """Take money. Raises PaymentDeclinedError if refused."""

    @abstractmethod
    def refund(self, *, idempotency_key: str, payment_id: str, amount: Decimal) -> RefundReceipt:
        """Give money back against an earlier charge."""


class FakePaymentGateway(PaymentGateway):
    """Test double. Ids are sequential so demo output is stable.

    `after_charge` runs after a new charge, outside the lock. Tests use it to
    simulate the clock moving while a slow payment is in flight.
    """

    def __init__(
        self,
        decline_users: Iterable[str] = (),
        after_charge: Callable[[], None] | None = None,
    ) -> None:
        self.decline_users: set[str] = set(decline_users)  # tests may edit
        self.after_charge = after_charge
        self._charges: dict[str, PaymentReceipt] = {}
        self._refunds: dict[str, RefundReceipt] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()  # guards _charges, _refunds, _ids

    def charge(self, *, idempotency_key: str, user_id: str, amount: Decimal) -> PaymentReceipt:
        with self._lock:
            seen = self._charges.get(idempotency_key)
            if seen is not None:
                if seen.amount != amount:
                    raise IdempotencyConflictError(
                        f"key {idempotency_key} already used for {seen.amount}"
                    )
                log.info("charge replayed for key %s", idempotency_key)
                return seen
            if user_id in self.decline_users:
                raise PaymentDeclinedError(f"card declined for {user_id}")
            receipt = PaymentReceipt(f"pay-{next(self._ids)}", idempotency_key, amount)
            self._charges[idempotency_key] = receipt
        log.info("charged %s as %s", amount, receipt.payment_id)
        if self.after_charge is not None:
            self.after_charge()
        return receipt

    def refund(self, *, idempotency_key: str, payment_id: str, amount: Decimal) -> RefundReceipt:
        with self._lock:
            seen = self._refunds.get(idempotency_key)
            if seen is not None:
                return seen
            receipt = RefundReceipt(f"ref-{next(self._ids)}", payment_id, amount)
            self._refunds[idempotency_key] = receipt
        log.info("refunded %s against %s", amount, payment_id)
        return receipt

    @property
    def charge_count(self) -> int:
        with self._lock:
            return len(self._charges)

    @property
    def total_charged(self) -> Decimal:
        with self._lock:
            return sum((r.amount for r in self._charges.values()), Decimal("0.00"))

    @property
    def total_refunded(self) -> Decimal:
        with self._lock:
            return sum((r.amount for r in self._refunds.values()), Decimal("0.00"))
