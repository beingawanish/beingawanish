"""Pure payment domain tests: outcome folding, idempotency, timeouts, reconciliation, the pivot."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from payment_svc.domain.payment import (
    CaptureFailure,
    CommandAction,
    DeclineReason,
    OutcomeKind,
    Payment,
    PaymentStatus,
    PspOutcome,
    ReconcileStep,
    ReplyKind,
    apply_outcome,
    give_up,
    on_authorize,
    on_capture,
    on_void,
    reconcile_step,
    timeout,
)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
P = Payment("p1", "o1", "c1", 1999, "EUR", PaymentStatus.PENDING)


def test_authorized_then_duplicate_is_noop() -> None:
    d = apply_outcome(P, PspOutcome(OutcomeKind.AUTHORIZED, psp_payment_id="psp1"), NOW)
    assert d.payment.status is PaymentStatus.AUTHORIZED and d.replies == (ReplyKind.AUTHORIZED,)
    assert d.payment.authorization_expires_at == NOW + timedelta(days=7)
    again = apply_outcome(d.payment, PspOutcome(OutcomeKind.AUTHORIZED), NOW)
    assert again.replies == () and again.payment == d.payment


def test_decline_maps_reason() -> None:
    d = apply_outcome(P, PspOutcome(OutcomeKind.DECLINED, decline_reason=DeclineReason.INSUFFICIENT_FUNDS), NOW)
    assert d.payment.status is PaymentStatus.DECLINED and d.payment.decline_reason is DeclineReason.INSUFFICIENT_FUNDS
    assert d.replies == (ReplyKind.DECLINED,)


def test_unknown_is_resolved_by_reconciliation_or_webhook() -> None:
    u = timeout(P, NOW)
    assert u.status is PaymentStatus.UNKNOWN and u.next_reconcile_at == NOW + timedelta(seconds=15)
    assert reconcile_step(u, PspOutcome(OutcomeKind.NOT_FOUND), NOW + timedelta(seconds=15)) is ReconcileStep.TRY_AGAIN
    assert reconcile_step(u, PspOutcome(OutcomeKind.AUTHORIZED), NOW + timedelta(seconds=15)) is ReconcileStep.APPLY
    assert reconcile_step(u, PspOutcome(OutcomeKind.NOT_FOUND), NOW + timedelta(minutes=2)) is ReconcileStep.GIVE_UP
    assert apply_outcome(u, PspOutcome(OutcomeKind.AUTHORIZED), NOW).replies == (ReplyKind.AUTHORIZED,)


def test_late_success_after_psp_timeout_is_voided_silently_once() -> None:
    declined = give_up(timeout(P, NOW), NOW + timedelta(minutes=2))
    assert declined.decline_reason is DeclineReason.PSP_TIMEOUT
    d = apply_outcome(declined, PspOutcome(OutcomeKind.AUTHORIZED, psp_payment_id="psp1"), NOW)
    assert d.void_at_psp and d.replies == () and d.payment.status is PaymentStatus.DECLINED
    assert not apply_outcome(d.payment, PspOutcome(OutcomeKind.AUTHORIZED), NOW).void_at_psp


def test_capture_success_and_failures() -> None:
    a = apply_outcome(P, PspOutcome(OutcomeKind.AUTHORIZED), NOW).payment
    pending = replace(a, status=PaymentStatus.CAPTURE_PENDING)
    ok = apply_outcome(pending, PspOutcome(OutcomeKind.CAPTURED), NOW)
    assert ok.payment.status is PaymentStatus.CAPTURED and ok.replies == (ReplyKind.CAPTURED,)
    retry = apply_outcome(
        pending, PspOutcome(OutcomeKind.CAPTURE_FAILED, capture_failure=CaptureFailure.PSP_ERROR, retryable=True), NOW
    )
    assert retry.payment.status is PaymentStatus.AUTHORIZED, "retryable failure leaves it capturable"
    final = apply_outcome(
        pending, PspOutcome(OutcomeKind.CAPTURE_FAILED, capture_failure=CaptureFailure.AUTHORIZATION_EXPIRED), NOW
    )
    assert final.payment.status is PaymentStatus.CAPTURE_FAILED and final.replies == (ReplyKind.CAPTURE_FAILED,)


def test_command_decisions() -> None:
    assert on_authorize(None) is CommandAction.CALL_PSP
    assert on_authorize(P) is CommandAction.CALL_PSP  # re-drive the idempotent PSP call
    assert on_authorize(timeout(P, NOW)) is CommandAction.WAIT
    a = apply_outcome(P, PspOutcome(OutcomeKind.AUTHORIZED), NOW).payment
    assert on_authorize(a) is CommandAction.REANSWER
    assert on_capture(a, NOW) == (CommandAction.CALL_PSP, None)
    assert on_capture(a, NOW + timedelta(days=8)) == (CommandAction.REFUSE, CaptureFailure.AUTHORIZATION_EXPIRED)
    captured = replace(a, status=PaymentStatus.CAPTURED)
    assert on_capture(captured, NOW) == (CommandAction.REANSWER, None)
    assert on_void(captured) is CommandAction.REFUSE, "never void past the pivot"
    assert on_void(a) is CommandAction.CALL_PSP
    assert on_void(None) is CommandAction.REANSWER
    assert on_void(replace(a, status=PaymentStatus.DECLINED)) is CommandAction.REANSWER
