"""Payments: deposit hold at pickup, capture and release at settlement.

PaymentGateway is the seam to a card processor. Every call carries an
idempotency key, the same contract real processors offer: send the same key
twice and the second call returns the first result instead of moving money
again. PaymentService derives each key from the reservation id and the step
("r1:hold", "r1:capture", ...), so a retry after a timeout replays the same
keys and cannot double-charge.
"""
import itertools
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from .errors import IdempotencyConflictError, PaymentStateError

log = logging.getLogger(__name__)


class PaymentGateway(ABC):
    @abstractmethod
    def hold(self, amount: float, key: str) -> str:
        """Reserve funds on the card. Returns a hold id."""

    @abstractmethod
    def capture(self, hold_id: str, amount: float, key: str) -> str:
        """Take up to the held amount. Returns a transaction id."""

    @abstractmethod
    def release(self, hold_id: str, key: str) -> str:
        """Free whatever is still held. Returns a transaction id."""

    @abstractmethod
    def charge(self, amount: float, key: str) -> str:
        """A plain charge with no hold. Returns a transaction id."""


@dataclass
class _Hold:
    amount: float
    captured: float = 0.0
    released: bool = False


class InMemoryPaymentGateway(PaymentGateway):
    """A fake that keeps the idempotency contract, so tests exercise retries."""

    def __init__(self):
        self._lock = threading.Lock()   # guards everything below
        self._results: dict[str, tuple[tuple, str]] = {}
        self._holds: dict[str, _Hold] = {}
        self._ids = itertools.count(1)
        self.executed: list[str] = []   # operations that really moved money

    def _once(self, key: str, request: tuple, action: Callable[[], str]) -> str:
        with self._lock:
            if key in self._results:
                seen_request, result = self._results[key]
                if seen_request != request:
                    raise IdempotencyConflictError(
                        f"key {key} reused for a different request")
                return result
            result = action()
            self._results[key] = (request, result)
            self.executed.append(f"{request[0]} {result}")
            return result

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    def hold(self, amount: float, key: str) -> str:
        def act() -> str:
            hold_id = self._new_id("H")
            self._holds[hold_id] = _Hold(amount)
            return hold_id
        return self._once(key, ("hold", amount), act)

    def capture(self, hold_id: str, amount: float, key: str) -> str:
        def act() -> str:
            hold = self._holds[hold_id]
            if hold.released or amount > hold.amount - hold.captured:
                raise PaymentStateError(f"cannot capture {amount} on {hold_id}")
            hold.captured = round(hold.captured + amount, 2)
            return self._new_id("C")
        return self._once(key, ("capture", hold_id, amount), act)

    def release(self, hold_id: str, key: str) -> str:
        def act() -> str:
            self._holds[hold_id].released = True
            return self._new_id("R")
        return self._once(key, ("release", hold_id), act)

    def charge(self, amount: float, key: str) -> str:
        return self._once(key, ("charge", amount), lambda: self._new_id("X"))

    def held(self, hold_id: str) -> float:
        with self._lock:
            hold = self._holds[hold_id]
            return 0.0 if hold.released else round(hold.amount - hold.captured, 2)


@dataclass(frozen=True)
class Settlement:
    reservation_id: str
    final: float
    captured: float
    released: float
    extra_charged: float


@dataclass
class PaymentRecord:
    reservation_id: str
    hold_id: str
    held: float
    settlement: Settlement | None = None


class PaymentService:
    def __init__(self, gateway: PaymentGateway):
        self._gateway = gateway
        self._lock = threading.RLock()   # one settlement at a time per service
        self._records: dict[str, PaymentRecord] = {}

    def record(self, reservation_id: str) -> PaymentRecord | None:
        with self._lock:
            return self._records.get(reservation_id)

    def place_hold(self, reservation_id: str, amount: float) -> PaymentRecord:
        if amount <= 0:
            raise ValueError("hold amount must be positive")
        with self._lock:
            existing = self._records.get(reservation_id)
            if existing is not None:
                return existing
            amount = round(amount, 2)
            hold_id = self._gateway.hold(amount, f"{reservation_id}:hold")
            record = PaymentRecord(reservation_id, hold_id, amount)
            self._records[reservation_id] = record
            log.info("hold %s: $%.2f for %s", hold_id, amount, reservation_id)
            return record

    def settle(self, reservation_id: str, final: float) -> Settlement:
        """Capture what is owed from the hold, release the rest, charge any excess."""
        if final < 0:
            raise ValueError("final amount must be >= 0")
        final = round(final, 2)
        with self._lock:
            record = self._records.get(reservation_id)
            if record is None:
                raise PaymentStateError(f"no hold for {reservation_id}")
            if record.settlement is not None:
                if record.settlement.final != final:
                    raise IdempotencyConflictError(
                        f"{reservation_id} already settled at "
                        f"${record.settlement.final:.2f}")
                return record.settlement
            rid, hold_id = reservation_id, record.hold_id
            captured = min(final, record.held)
            if captured > 0:
                self._gateway.capture(hold_id, captured, f"{rid}:capture")
            released = round(record.held - captured, 2)
            if released > 0:
                self._gateway.release(hold_id, f"{rid}:release")
            extra = round(final - captured, 2)
            if extra > 0:
                self._gateway.charge(extra, f"{rid}:extra")
            record.settlement = Settlement(rid, final, captured, released, extra)
            log.info("settled %s: final $%.2f", rid, final)
            return record.settlement

