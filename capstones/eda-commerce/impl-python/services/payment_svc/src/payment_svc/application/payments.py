"""payment-svc use cases: authorise, capture, void, refund, apply PSP notifications, reconcile.

Each runs in the caller's unit of work. PSP calls happen inside that transaction, after the payment
row is written and before commit. That is safe only because every PSP call carries our business id
as its idempotency key (ADR-0006 layer 3): if the transaction rolls back and the command is
redelivered, the PSP returns the same result instead of charging again. The cost is a transaction
held open for up to the PSP timeout (5 s); DB_POOL_SIZE must cover the consumer threads.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from edacommon.envelope import Causation, current_causation
from edacommon.errors import NonRetryable
from edacommon.logging import get_logger
from payment_svc.application import messages
from payment_svc.application.ports import EventPublisher, PaymentRepository, PspGateway, PspTimeout
from payment_svc.domain.payment import (
    RECONCILE_INTERVAL,
    CommandAction,
    OutcomeKind,
    Payment,
    PaymentStatus,
    PspOutcome,
    ReconcileStep,
    Refund,
    RefundStatus,
    ReplyKind,
    apply_outcome,
    apply_refund_outcome,
    give_up,
    on_authorize,
    on_capture,
    on_refund,
    on_void,
    reconcile_step,
    timeout,
)

log = get_logger(__name__)

_REANSWER = {
    PaymentStatus.AUTHORIZED: ReplyKind.AUTHORIZED,
    PaymentStatus.CAPTURE_PENDING: ReplyKind.AUTHORIZED,
    PaymentStatus.CAPTURED: ReplyKind.AUTHORIZED,
    PaymentStatus.CAPTURE_FAILED: ReplyKind.AUTHORIZED,
    PaymentStatus.DECLINED: ReplyKind.DECLINED,
}


def _command_id() -> str | None:
    c = current_causation()
    return c.causation_id if c else None


@dataclass
class Payments:
    repo: PaymentRepository
    psp: PspGateway
    events: EventPublisher

    # ------------------------------------------------------------------------------- helpers
    def _apply(self, p: Payment, outcome: PspOutcome, now: datetime, causation: Causation | None = None) -> Payment:
        d = apply_outcome(p, outcome, now)
        q = d.payment
        if d.void_at_psp:
            log.warning("late PSP success after PSP_TIMEOUT: voiding", payment_id=p.payment_id)
            self._call_void(q, now)
            self.repo.record_attempt(p.payment_id, "late-void", "voided", now)
        self.repo.save(q, now)
        for kind in d.replies:
            self.events.publish(messages.reply(q, kind, now, causation))
        return q

    def _async_causation(self, p: Payment) -> Causation:
        # Replies that arrive by webhook or timer are still caused by the command that asked for them.
        return Causation(correlation_id=p.order_id, causation_id=p.last_command_id)

    def _call_void(self, p: Payment, now: datetime) -> PspOutcome:
        try:
            return self.psp.void(payment_id=p.payment_id, psp_payment_id=p.psp_payment_id)
        except PspTimeout:
            self.repo.record_attempt(p.payment_id, "void", "timeout", now)
            return PspOutcome(OutcomeKind.PENDING)

    # --------------------------------------------------------------------------- AuthorizePayment
    def authorize(self, *, order_id: str, payment_id: str, customer_id: str, amount_minor: int, currency: str,
                  token: str, now: datetime) -> None:
        existing = self.repo.get(payment_id, for_update=True)
        action = on_authorize(existing)
        if action is CommandAction.REANSWER and existing is not None:
            self.events.publish(messages.reply(existing, _REANSWER[existing.status], now))
            return
        if action is CommandAction.WAIT:
            log.info("authorize resend while outcome pending; waiting", payment_id=payment_id)
            return
        p = existing or Payment(payment_id=payment_id, order_id=order_id, customer_id=customer_id,
                                amount_minor=amount_minor, currency=currency, status=PaymentStatus.PENDING)
        p = replace(p, last_command_id=_command_id() or p.last_command_id)
        self.repo.save(p, now)
        try:
            outcome = self.psp.authorize(payment_id=payment_id, amount_minor=amount_minor, currency=currency, token=token)
        except PspTimeout:
            self.repo.record_attempt(payment_id, "authorize", "timeout", now)
            self.repo.save(timeout(p, now), now)
            log.warning("PSP timeout on authorize: outcome unknown, reconciling", payment_id=payment_id)
            return
        self.repo.record_attempt(payment_id, "authorize", outcome.kind.value, now)
        if outcome.psp_payment_id:
            p = replace(p, psp_payment_id=outcome.psp_payment_id)
        self._apply(p, outcome, now)

    # ----------------------------------------------------------------------------- CapturePayment
    def capture(self, *, payment_id: str, amount_minor: int, now: datetime) -> None:
        p = self.repo.get(payment_id, for_update=True)
        if p is None:
            raise NonRetryable(f"capture for unknown payment {payment_id}")
        if amount_minor > p.amount_minor:
            raise NonRetryable(f"capture {amount_minor} exceeds authorised {p.amount_minor}")
        action, failure = on_capture(p, now)
        if action is CommandAction.REANSWER:
            kind = ReplyKind.CAPTURED if p.status is PaymentStatus.CAPTURED else ReplyKind.CAPTURE_FAILED
            self.events.publish(messages.reply(p, kind, now))
            return
        if action is CommandAction.REFUSE:
            if failure is None:
                raise NonRetryable(f"capture refused for payment in {p.status}")
            q = replace(p, status=PaymentStatus.CAPTURE_FAILED, capture_failure=failure, capture_failed_at=now)
            self.repo.save(q, now)
            self.events.publish(messages.reply(q, ReplyKind.CAPTURE_FAILED, now))
            return
        p = replace(p, status=PaymentStatus.CAPTURE_PENDING, last_command_id=_command_id() or p.last_command_id)
        self.repo.save(p, now)
        try:
            outcome = self.psp.capture(payment_id=payment_id, psp_payment_id=p.psp_payment_id,
                                       amount_minor=amount_minor, currency=p.currency)
        except PspTimeout:
            # The saga's capture deadline resends; the PSP dedupes on the capture key.
            self.repo.record_attempt(payment_id, "capture", "timeout", now)
            return
        self.repo.record_attempt(payment_id, "capture", outcome.kind.value, now)
        self._apply(p, outcome, now)

    # -------------------------------------------------------------------------------- VoidPayment
    def void(self, *, order_id: str, payment_id: str, now: datetime) -> None:
        p = self.repo.get(payment_id, for_update=True)
        action = on_void(p)
        if p is None:
            tomb = Payment(payment_id=payment_id, order_id=order_id, customer_id="", amount_minor=0, currency="XXX",
                           status=PaymentStatus.VOIDED, voided_at=now)
            self.repo.save(tomb, now)
            self.events.publish(messages.reply(tomb, ReplyKind.VOIDED, now))
            return
        if action is CommandAction.REANSWER:
            q = p if p.voided_at else replace(p, voided_at=now)
            if q is not p:
                self.repo.save(q, now)
            self.events.publish(messages.reply(q, ReplyKind.VOIDED, now))
            return
        if action is CommandAction.REFUSE:
            raise NonRetryable(f"void refused: payment {payment_id} is {p.status} (past the pivot)")
        p = replace(p, status=PaymentStatus.VOID_PENDING, last_command_id=_command_id() or p.last_command_id)
        self.repo.save(p, now)
        outcome = self._call_void(p, now)
        self.repo.record_attempt(payment_id, "void", outcome.kind.value, now)
        self._apply(p, outcome, now)

    # ------------------------------------------------------------------------------ RefundPayment
    def refund(self, *, order_id: str, payment_id: str, refund_id: str, return_id: str | None, amount_minor: int,
               currency: str, now: datetime) -> None:
        r = self.repo.get_refund(refund_id, for_update=True)
        if on_refund(r) is CommandAction.REANSWER and r is not None:
            self.events.publish(messages.refund_reply(r, now))
            return
        p = self.repo.get(payment_id)
        r = r or Refund(refund_id=refund_id, payment_id=payment_id, order_id=order_id, return_id=return_id,
                        amount_minor=amount_minor, currency=currency, status=RefundStatus.PENDING)
        r = replace(r, status=RefundStatus.PENDING, last_command_id=_command_id() or r.last_command_id)
        if p is None or p.status is not PaymentStatus.CAPTURED:
            failed = replace(r, status=RefundStatus.FAILED, failure_reason="payment not captured", retryable=False,
                             finished_at=now)
            self.repo.save_refund(failed, now)
            self.events.publish(messages.refund_reply(failed, now))
            return
        self.repo.save_refund(r, now)
        try:
            outcome = self.psp.refund(refund_id=refund_id, payment_id=payment_id, psp_payment_id=p.psp_payment_id,
                                      amount_minor=amount_minor, currency=currency)
        except PspTimeout:
            self.repo.record_attempt(payment_id, "refund", "timeout", now, refund_id)
            return
        self.repo.record_attempt(payment_id, "refund", outcome.kind.value, now, refund_id)
        self.apply_refund(r, outcome, now)

    def apply_refund(self, r: Refund, outcome: PspOutcome, now: datetime, causation: Causation | None = None) -> None:
        q, emit = apply_refund_outcome(r, outcome, now)
        if q is not r:
            self.repo.save_refund(q, now)
        if emit:
            self.events.publish(messages.refund_reply(q, now, causation))

    # ------------------------------------------------------------------------ PSP notifications
    def on_psp_outcome(self, *, merchant_reference: str, outcome: PspOutcome, now: datetime) -> None:
        """Apply a stored webhook. ``merchantReference`` is our paymentId or refundId."""
        if outcome.kind in (OutcomeKind.REFUNDED, OutcomeKind.REFUND_FAILED):
            r = self.repo.get_refund(merchant_reference, for_update=True)
            if r is None:
                log.warning("refund notification for unknown refund", refund_id=merchant_reference)
                return
            self.apply_refund(r, outcome, now, Causation(correlation_id=r.order_id, causation_id=r.last_command_id))
            return
        p = self.repo.get(merchant_reference, for_update=True)
        if p is None:
            log.warning("PSP notification for unknown payment", payment_id=merchant_reference)
            return
        self._apply(p, outcome, now, self._async_causation(p))

    # ---------------------------------------------------------------------------- reconciliation
    def reconcile_due(self, now: datetime, limit: int = 50) -> int:
        due = self.repo.due_reconciliation(now, limit)
        for p in due:
            try:
                found = self.psp.lookup(payment_id=p.payment_id)
            except PspTimeout:
                found = PspOutcome(OutcomeKind.NOT_FOUND)
            step = reconcile_step(p, found, now)
            self.repo.record_attempt(p.payment_id, "lookup", found.kind.value, now)
            if step is ReconcileStep.APPLY:
                self._apply(p, found, now, self._async_causation(p))
            elif step is ReconcileStep.GIVE_UP:
                # "void p1 (safe even if nothing exists)", then decline PSP_TIMEOUT. Never both.
                self._call_void(p, now)
                q = give_up(p, now)
                self.repo.save(q, now)
                self.events.publish(messages.reply(q, ReplyKind.DECLINED, now, self._async_causation(p)))
            else:
                self.repo.save(replace(p, next_reconcile_at=now + RECONCILE_INTERVAL), now)
        return len(due)
