"""Ports of payment-svc. The PSP port is implemented by the fake PSP today and by a real PSP client
tomorrow, without touching this layer or the domain."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from edacommon.envelope import OutgoingMessage
from payment_svc.domain.payment import Payment, PspOutcome, Refund


class PspTimeout(Exception):
    """The PSP did not answer in time. The outcome is unknown, not failed (architecture §5.6)."""


class PspGateway(Protocol):
    def authorize(self, *, payment_id: str, amount_minor: int, currency: str, token: str) -> PspOutcome: ...

    def capture(self, *, payment_id: str, psp_payment_id: str | None, amount_minor: int, currency: str) -> PspOutcome: ...

    def void(self, *, payment_id: str, psp_payment_id: str | None) -> PspOutcome: ...

    def refund(self, *, refund_id: str, payment_id: str, psp_payment_id: str | None, amount_minor: int,
               currency: str) -> PspOutcome: ...

    def lookup(self, *, payment_id: str) -> PspOutcome: ...


class PaymentRepository(Protocol):
    def get(self, payment_id: str, *, for_update: bool = False) -> Payment | None: ...

    def save(self, p: Payment, now: datetime) -> None: ...

    def due_reconciliation(self, now: datetime, limit: int) -> list[Payment]: ...

    def record_attempt(self, payment_id: str, operation: str, outcome: str, now: datetime, detail: str | None = None) -> None: ...

    def get_refund(self, refund_id: str, *, for_update: bool = False) -> Refund | None: ...

    def save_refund(self, r: Refund, now: datetime) -> None: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...
