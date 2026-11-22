"""Payment domain: the state of one authorisation and its capture, void and refunds. Pure.

The PSP's vocabulary never reaches this module (anti-corruption layer, architecture §2): the PSP
adapter translates status codes into :class:`PspOutcome`, and this module decides what that means
for the payment and which reply the order saga gets.

Two rules carry most of the weight:

* A timeout means *we do not know* (architecture §5.6). The payment becomes ``UNKNOWN`` and is
  reconciled; after the window it is voided and declined as ``PSP_TIMEOUT``.
* A late ``authorization.succeeded`` after we declared ``PSP_TIMEOUT`` is voided at once and the saga
  never hears about it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum

AUTHORIZATION_VALIDITY = timedelta(days=7)
RECONCILE_INTERVAL = timedelta(seconds=15)
RECONCILE_WINDOW = timedelta(minutes=2)


class PaymentStatus(StrEnum):
    PENDING = "PENDING"                # authorise sent, result will come by webhook
    UNKNOWN = "UNKNOWN"                # PSP did not answer: reconciling
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    CAPTURE_PENDING = "CAPTURE_PENDING"
    CAPTURED = "CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"  # non-retryable: a human decides (past the pivot)
    VOID_PENDING = "VOID_PENDING"
    VOIDED = "VOIDED"


class DeclineReason(StrEnum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_DECLINED = "CARD_DECLINED"
    FRAUD_SUSPECTED = "FRAUD_SUSPECTED"
    PSP_TIMEOUT = "PSP_TIMEOUT"
    PSP_ERROR = "PSP_ERROR"


class CaptureFailure(StrEnum):
    AUTHORIZATION_EXPIRED = "AUTHORIZATION_EXPIRED"
    PSP_ERROR = "PSP_ERROR"


class OutcomeKind(StrEnum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    CAPTURED = "CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"
    REFUND_FAILED = "REFUND_FAILED"
    NOT_FOUND = "NOT_FOUND"


@dataclass(frozen=True, slots=True)
class PspOutcome:
    """What the PSP told us, in our words."""

    kind: OutcomeKind
    psp_payment_id: str | None = None
    psp_reference: str | None = None
    decline_reason: DeclineReason | None = None
    capture_failure: CaptureFailure | None = None
    refund_failure: str | None = None
    retryable: bool = False
    at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Payment:
    payment_id: str
    order_id: str
    customer_id: str
    amount_minor: int
    currency: str
    status: PaymentStatus
    psp_payment_id: str | None = None
    psp_reference: str | None = None
    decline_reason: DeclineReason | None = None
    capture_failure: CaptureFailure | None = None
    authorized_at: datetime | None = None
    authorization_expires_at: datetime | None = None
    declined_at: datetime | None = None
    captured_at: datetime | None = None
    capture_failed_at: datetime | None = None
    voided_at: datetime | None = None
    unknown_since: datetime | None = None
    next_reconcile_at: datetime | None = None
    late_success_voided: bool = False
    last_command_id: str | None = None  # causation of asynchronous replies


class ReplyKind(StrEnum):
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    CAPTURED = "CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    VOIDED = "VOIDED"


@dataclass(frozen=True, slots=True)
class Decision:
    payment: Payment
    replies: tuple[ReplyKind, ...] = ()
    void_at_psp: bool = False


def apply_outcome(p: Payment, o: PspOutcome, now: datetime) -> Decision:
    """Fold a PSP outcome (synchronous answer, webhook or reconciliation lookup) into the payment.

    Idempotent: applying the same outcome twice changes nothing the second time and emits nothing.
    """
    at = o.at or now
    s = p.status
    if o.kind is OutcomeKind.AUTHORIZED:
        if s in (PaymentStatus.PENDING, PaymentStatus.UNKNOWN):
            q = replace(p, status=PaymentStatus.AUTHORIZED, psp_payment_id=o.psp_payment_id or p.psp_payment_id,
                        psp_reference=o.psp_reference or p.psp_reference, authorized_at=at,
                        authorization_expires_at=at + AUTHORIZATION_VALIDITY, unknown_since=None, next_reconcile_at=None)
            return Decision(q, (ReplyKind.AUTHORIZED,))
        if s is PaymentStatus.DECLINED and p.decline_reason is DeclineReason.PSP_TIMEOUT and not p.late_success_voided:
            # Late success after we gave up: void it, tell nobody (ACL, architecture §5.6).
            return Decision(replace(p, late_success_voided=True, psp_payment_id=o.psp_payment_id or p.psp_payment_id),
                            (), void_at_psp=True)
        return Decision(p)
    if o.kind is OutcomeKind.DECLINED:
        if s in (PaymentStatus.PENDING, PaymentStatus.UNKNOWN):
            q = replace(p, status=PaymentStatus.DECLINED, decline_reason=o.decline_reason or DeclineReason.CARD_DECLINED,
                        psp_reference=o.psp_reference or p.psp_reference, declined_at=at, unknown_since=None,
                        next_reconcile_at=None)
            return Decision(q, (ReplyKind.DECLINED,))
        return Decision(p)
    if o.kind is OutcomeKind.CAPTURED:
        if s in (PaymentStatus.CAPTURE_PENDING, PaymentStatus.AUTHORIZED):
            q = replace(p, status=PaymentStatus.CAPTURED, captured_at=at,
                        psp_reference=o.psp_reference or p.psp_reference)
            return Decision(q, (ReplyKind.CAPTURED,))
        return Decision(p)
    if o.kind is OutcomeKind.CAPTURE_FAILED:
        if s is PaymentStatus.CAPTURE_PENDING:
            failure = o.capture_failure or CaptureFailure.PSP_ERROR
            status = PaymentStatus.AUTHORIZED if o.retryable else PaymentStatus.CAPTURE_FAILED
            q = replace(p, status=status, capture_failure=failure, capture_failed_at=at)
            return Decision(q, (ReplyKind.CAPTURE_FAILED,))
        return Decision(p)
    if o.kind is OutcomeKind.VOIDED:
        if s in (PaymentStatus.VOID_PENDING, PaymentStatus.AUTHORIZED, PaymentStatus.PENDING, PaymentStatus.UNKNOWN):
            return Decision(replace(p, status=PaymentStatus.VOIDED, voided_at=at, unknown_since=None,
                                    next_reconcile_at=None), (ReplyKind.VOIDED,))
        return Decision(p)
    return Decision(p)


class CommandAction(StrEnum):
    CALL_PSP = "CALL_PSP"
    REANSWER = "REANSWER"   # re-emit the original reply (resend with the same business id)
    WAIT = "WAIT"           # a result is on its way (webhook or reconciliation)
    REFUSE = "REFUSE"       # cannot be done (e.g. void after capture): needs a human


def on_authorize(p: Payment | None) -> CommandAction:
    if p is None:
        return CommandAction.CALL_PSP
    if p.status in (PaymentStatus.AUTHORIZED, PaymentStatus.DECLINED, PaymentStatus.CAPTURED,
                    PaymentStatus.CAPTURE_PENDING, PaymentStatus.CAPTURE_FAILED):
        return CommandAction.REANSWER
    if p.status is PaymentStatus.PENDING:
        return CommandAction.CALL_PSP  # re-drive: the PSP is idempotent on paymentId
    return CommandAction.WAIT          # UNKNOWN (reconciling), VOID_PENDING, VOIDED


def on_capture(p: Payment, now: datetime) -> tuple[CommandAction, CaptureFailure | None]:
    if p.status is PaymentStatus.CAPTURED:
        return CommandAction.REANSWER, None
    if p.status is PaymentStatus.CAPTURE_FAILED:
        return CommandAction.REANSWER, p.capture_failure
    if p.status in (PaymentStatus.AUTHORIZED, PaymentStatus.CAPTURE_PENDING):
        if p.authorization_expires_at is not None and now >= p.authorization_expires_at:
            return CommandAction.REFUSE, CaptureFailure.AUTHORIZATION_EXPIRED
        return CommandAction.CALL_PSP, None
    return CommandAction.REFUSE, None


def on_void(p: Payment | None) -> CommandAction:
    if p is None:
        return CommandAction.REANSWER  # nothing was ever held: answer "voided" (tombstone)
    if p.status is PaymentStatus.VOIDED or p.status is PaymentStatus.DECLINED:
        return CommandAction.REANSWER
    if p.status in (PaymentStatus.CAPTURED, PaymentStatus.CAPTURE_PENDING, PaymentStatus.CAPTURE_FAILED):
        return CommandAction.REFUSE    # past the pivot: never void a capture (ADR-0015)
    return CommandAction.CALL_PSP      # PENDING, UNKNOWN, AUTHORIZED, VOID_PENDING


def timeout(p: Payment, now: datetime) -> Payment:
    return replace(p, status=PaymentStatus.UNKNOWN, unknown_since=now, next_reconcile_at=now + RECONCILE_INTERVAL)


class ReconcileStep(StrEnum):
    APPLY = "APPLY"
    TRY_AGAIN = "TRY_AGAIN"
    GIVE_UP = "GIVE_UP"   # void at the PSP (safe even if nothing exists) and decline PSP_TIMEOUT


def reconcile_step(p: Payment, lookup: PspOutcome, now: datetime) -> ReconcileStep:
    if lookup.kind in (OutcomeKind.AUTHORIZED, OutcomeKind.DECLINED):
        return ReconcileStep.APPLY
    assert p.unknown_since is not None
    if now - p.unknown_since >= RECONCILE_WINDOW:
        return ReconcileStep.GIVE_UP
    return ReconcileStep.TRY_AGAIN


def give_up(p: Payment, now: datetime) -> Payment:
    return replace(p, status=PaymentStatus.DECLINED, decline_reason=DeclineReason.PSP_TIMEOUT, declined_at=now,
                   unknown_since=None, next_reconcile_at=None)


# ------------------------------------------------------------------------------------------ refunds
class RefundStatus(StrEnum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Refund:
    refund_id: str
    payment_id: str
    order_id: str
    return_id: str | None
    amount_minor: int
    currency: str
    status: RefundStatus
    psp_reference: str | None = None
    failure_reason: str | None = None
    retryable: bool = False
    finished_at: datetime | None = None
    last_command_id: str | None = None


def on_refund(r: Refund | None) -> CommandAction:
    if r is None or r.status is RefundStatus.FAILED or r.status is RefundStatus.PENDING:
        return CommandAction.CALL_PSP  # same refundId = same PSP idempotency key: never refunds twice
    return CommandAction.REANSWER


def apply_refund_outcome(r: Refund, o: PspOutcome, now: datetime) -> tuple[Refund, bool]:
    """Returns (refund, emit_reply)."""
    if r.status is not RefundStatus.PENDING:
        return r, False
    if o.kind is OutcomeKind.REFUNDED:
        return replace(r, status=RefundStatus.SUCCEEDED, psp_reference=o.psp_reference, finished_at=o.at or now), True
    if o.kind is OutcomeKind.REFUND_FAILED:
        return replace(r, status=RefundStatus.FAILED, failure_reason=o.refund_failure or "refund failed",
                       retryable=o.retryable, finished_at=o.at or now), True
    return r, False
