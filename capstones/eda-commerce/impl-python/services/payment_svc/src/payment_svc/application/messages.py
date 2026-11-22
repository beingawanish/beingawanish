"""Payment decisions -> replies on payment.events.v1 (keyed by orderId)."""

from __future__ import annotations

from datetime import datetime

from contracts_py.records import (
    PaymentAuthorized,
    PaymentCaptured,
    PaymentCaptureFailed,
    PaymentDeclined,
    PaymentVoided,
    RefundFailed,
    RefundSucceeded,
)
from edacommon.envelope import Causation, OutgoingMessage
from payment_svc.domain.payment import CaptureFailure, Payment, Refund, ReplyKind


def _money(minor: int, currency: str) -> dict[str, object]:
    return {"amountMinor": minor, "currency": currency}


def _msg(cls: type, p_order: str, aggregate_id: str, body: dict[str, object], causation: Causation | None) -> OutgoingMessage:
    return OutgoingMessage(topic=cls.TOPIC, record_type=cls.AVRO_NAME, key=p_order, body=body,  # type: ignore[attr-defined]
                           aggregate_type="Payment", aggregate_id=aggregate_id, causation=causation)


def reply(p: Payment, kind: ReplyKind, now: datetime, causation: Causation | None = None) -> OutgoingMessage:
    base: dict[str, object] = {"orderId": p.order_id, "paymentId": p.payment_id}
    if kind is ReplyKind.AUTHORIZED:
        assert p.authorized_at and p.authorization_expires_at
        return _msg(PaymentAuthorized, p.order_id, p.payment_id, {
            **base, "pspReference": p.psp_reference or p.psp_payment_id or "", "amount": _money(p.amount_minor, p.currency),
            "authorizedAt": p.authorized_at, "authorizationExpiresAt": p.authorization_expires_at}, causation)
    if kind is ReplyKind.DECLINED:
        return _msg(PaymentDeclined, p.order_id, p.payment_id, {
            **base, "reason": (p.decline_reason.value if p.decline_reason else "UNKNOWN"),
            "pspReference": p.psp_reference, "declinedAt": p.declined_at or now}, causation)
    if kind is ReplyKind.CAPTURED:
        return _msg(PaymentCaptured, p.order_id, p.payment_id, {
            **base, "amount": _money(p.amount_minor, p.currency), "pspReference": p.psp_reference or p.psp_payment_id or "",
            "capturedAt": p.captured_at or now}, causation)
    if kind is ReplyKind.CAPTURE_FAILED:
        failure = p.capture_failure or CaptureFailure.PSP_ERROR
        return _msg(PaymentCaptureFailed, p.order_id, p.payment_id, {
            **base, "reason": failure.value, "retryable": failure is CaptureFailure.PSP_ERROR,
            "failedAt": p.capture_failed_at or now}, causation)
    return _msg(PaymentVoided, p.order_id, p.payment_id, {**base, "voidedAt": p.voided_at or now}, causation)


def capture_refused(p: Payment, failure: CaptureFailure, now: datetime) -> OutgoingMessage:
    return _msg(PaymentCaptureFailed, p.order_id, p.payment_id, {
        "orderId": p.order_id, "paymentId": p.payment_id, "reason": failure.value,
        "retryable": failure is CaptureFailure.PSP_ERROR, "failedAt": now}, None)


def refund_reply(r: Refund, now: datetime, causation: Causation | None = None) -> OutgoingMessage:
    base: dict[str, object] = {"orderId": r.order_id, "paymentId": r.payment_id, "refundId": r.refund_id,
                               "returnId": r.return_id}
    if r.status.value == "SUCCEEDED":
        return _msg(RefundSucceeded, r.order_id, r.refund_id, {
            **base, "amount": _money(r.amount_minor, r.currency), "pspReference": r.psp_reference or "",
            "refundedAt": r.finished_at or now}, causation)
    return _msg(RefundFailed, r.order_id, r.refund_id, {
        **base, "reason": r.failure_reason or "refund failed", "retryable": r.retryable,
        "failedAt": r.finished_at or now}, causation)
