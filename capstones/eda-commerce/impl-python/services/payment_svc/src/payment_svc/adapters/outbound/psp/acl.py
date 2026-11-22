"""Anti-corruption layer: PSP vocabulary (webhooks.yaml ``PspNotification``) -> domain outcomes.

This is the only place that knows ``authorization.failed`` or ``insufficient_funds``. A real PSP
adapter reuses it (or brings its own mapping) and nothing else changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from payment_svc.domain.payment import CaptureFailure, DeclineReason, OutcomeKind, PspOutcome

_DECLINE = {
    "insufficient_funds": DeclineReason.INSUFFICIENT_FUNDS,
    "card_declined": DeclineReason.CARD_DECLINED,
    "fraud_suspected": DeclineReason.FRAUD_SUSPECTED,
    "processing_error": DeclineReason.PSP_ERROR,
}


def _at(v: str | None) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(v.replace("Z", "+00:00"))


def outcome_from_notification(n: dict[str, Any]) -> tuple[str, PspOutcome]:
    """Return (merchantReference, outcome) for a PSP notification."""
    et = n["eventType"]
    code = n.get("failureCode")
    psp_id = n.get("pspPaymentId")
    ref = n["merchantReference"]
    at = _at(n.get("occurredAt"))
    if et == "authorization.succeeded":
        return ref, PspOutcome(OutcomeKind.AUTHORIZED, psp_payment_id=psp_id, psp_reference=psp_id, at=at)
    if et == "authorization.failed":
        return ref, PspOutcome(OutcomeKind.DECLINED, psp_payment_id=psp_id, psp_reference=psp_id,
                               decline_reason=_DECLINE.get(code or "", DeclineReason.CARD_DECLINED), at=at)
    if et == "capture.succeeded":
        return ref, PspOutcome(OutcomeKind.CAPTURED, psp_payment_id=psp_id, psp_reference=psp_id, at=at)
    if et == "capture.failed":
        expired = code == "authorization_expired"
        return ref, PspOutcome(OutcomeKind.CAPTURE_FAILED, psp_payment_id=psp_id,
                               capture_failure=CaptureFailure.AUTHORIZATION_EXPIRED if expired else CaptureFailure.PSP_ERROR,
                               retryable=not expired, at=at)
    if et == "void.succeeded":
        return ref, PspOutcome(OutcomeKind.VOIDED, psp_payment_id=psp_id, at=at)
    if et == "refund.succeeded":
        return ref, PspOutcome(OutcomeKind.REFUNDED, psp_payment_id=psp_id, psp_reference=n.get("pspEventId"), at=at)
    if et == "refund.failed":
        return ref, PspOutcome(OutcomeKind.REFUND_FAILED, psp_payment_id=psp_id, refund_failure=code or "refund failed",
                               retryable=code in (None, "processing_error"), at=at)
    raise ValueError(f"unknown PSP event type {et!r}")
