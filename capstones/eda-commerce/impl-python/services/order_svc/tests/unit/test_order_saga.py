"""Every row of the order saga state table (architecture §5.1/§5.2) plus late, duplicate and
out-of-order replies in every waiting state (checklist §11 "Domain")."""

from __future__ import annotations

from datetime import timedelta

import pytest

from order_svc.domain import saga as S

from .sagahelp import CFG, Run

W = S.State


# ------------------------------------------------------------------------------------ happy path
def test_happy_path_to_delivered() -> None:
    r = Run.started()
    assert r.state is W.RESERVING_STOCK and r.cmd_names() == ["ReserveStock"] and r.evt_names() == ["OrderPlaced"]
    assert r.deadline == r.now + CFG.stock
    r.stock_reserved()
    assert r.state is W.AUTHORIZING_PAYMENT and r.commands[-1].name == "AuthorizePayment"
    r.authorized()
    assert r.state is W.COMMITTING_STOCK and r.commands[-1].name == "CommitReservation"
    d = r.committed()
    assert r.state is W.AWAITING_FULFILMENT_ACK and d.decision_reached
    assert [c.name for c in d.commands] == ["RequestFulfilment"] and [e.name for e in d.events] == ["OrderConfirmed"]
    assert d.commands[0].params["attempt"] == 1
    r.accepted()
    assert r.state is W.FULFILLING and r.deadline == r.now + CFG.dispatch
    r.packed()
    assert r.state is W.PACKED
    d = r.dispatched()
    assert r.state is W.CAPTURING and [c.name for c in d.commands] == ["CapturePayment"] and r.data.invoice_id
    r.send(S.ShipmentCreated("ship-1", "fake-carrier", "FC1", True))
    d = r.captured()
    assert r.state is W.SHIPPED and [e.name for e in d.events] == ["OrderShipped", "InvoiceIssued"]
    assert r.deadline == r.now + timedelta(days=30)
    d = r.delivered()
    assert r.state is W.DELIVERED and d.terminal and d.outcome == "DELIVERED" and r.deadline is None
    assert r.cmd_names() == ["ReserveStock", "AuthorizePayment", "CommitReservation", "RequestFulfilment", "CapturePayment"]
    assert r.evt_names() == ["OrderPlaced", "OrderConfirmed", "OrderShipped", "InvoiceIssued", "OrderDelivered"]


def test_ids_are_minted_once_and_reused_for_resends() -> None:
    r = Run.started()
    rid = r.data.reservation_id
    r.deadline_fires()
    assert r.commands[-1] == S.Command("ReserveStock", rid, {"ttlSeconds": 900})
    r.stock_reserved()
    pid = r.data.payment_id
    r.deadline_fires()
    assert r.commands[-1].business_id == pid
    r.authorized()
    r.committed()
    fid = r.data.fulfilment_id
    r.deadline_fires()
    assert r.commands[-1].business_id == fid and r.commands[-1].params["attempt"] == 2


# ------------------------------------------------------------------------------ RESERVING_STOCK
def test_out_of_stock_cancels_without_compensation() -> None:
    r = Run.started()
    d = r.send(S.StockReservationRejected(r.data.reservation_id, "SKU-1005 short"))
    assert r.state is W.CANCELLED and d.outcome == "CANCELLED" and d.decision_reached
    assert r.data.cancel_reason == "OUT_OF_STOCK" and r.cmd_names() == ["ReserveStock"]
    assert r.evt_names()[-1] == "OrderCancelled"


def test_stock_deadline_resends_twice_then_cancels_with_release() -> None:
    r = Run.started()
    r.deadline_fires()
    r.deadline_fires()
    assert r.cmd_names() == ["ReserveStock"] * 3 and r.attempts == 2
    d = r.deadline_fires()
    assert r.state is W.CANCELLING and [c.name for c in d.commands] == ["ReleaseReservation"]
    assert r.data.cancel_reason == "SAGA_TIMEOUT" and r.deadline == r.now + CFG.compensation
    r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.state is W.CANCELLED


def test_late_stock_reserved_while_cancelling_is_already_covered_by_release() -> None:
    r = Run.started()
    for _ in range(3):
        r.deadline_fires()
    assert r.send(S.StockReserved(r.data.reservation_id)).ignored
    r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.state is W.CANCELLED


def test_reply_for_another_reservation_is_ignored() -> None:
    r = Run.started()
    assert r.send(S.StockReserved("someone-else")).ignored
    assert r.state is W.RESERVING_STOCK


# -------------------------------------------------------------------------- AUTHORIZING_PAYMENT
def test_decline_releases_reservation_then_cancelled_without_void() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    d = r.send(S.PaymentDeclined(r.data.payment_id or "", "CARD_DECLINED"))
    assert r.state is W.CANCELLING and [c.name for c in d.commands] == ["ReleaseReservation"]
    assert d.decision_reached
    d = r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.state is W.CANCELLED and r.data.cancel_reason == "PAYMENT_DECLINED" and not r.data.payment_voided
    assert "VoidPayment" not in r.cmd_names()


def test_payment_deadline_resends_once_then_cancels_with_void_and_release() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.deadline_fires()
    assert r.cmd_names().count("AuthorizePayment") == 2
    d = r.deadline_fires()
    assert r.state is W.CANCELLING and sorted(c.name for c in d.commands) == ["ReleaseReservation", "VoidPayment"]
    r.send(S.PaymentVoided(r.data.payment_id or ""))
    assert r.state is W.CANCELLING
    r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.state is W.CANCELLED and r.data.payment_voided


def test_reservation_expires_before_payment_finishes() -> None:
    """Architecture §5.7."""
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    d = r.send(S.ReservationExpired(r.data.reservation_id))
    assert r.state is W.AUTHORIZING_PAYMENT and r.data.reservation_expired and not d.commands
    d = r.authorized()
    assert r.state is W.CANCELLING and [c.name for c in d.commands] == ["VoidPayment"]
    r.send(S.PaymentVoided(r.data.payment_id or ""))
    assert r.state is W.CANCELLED and r.data.cancel_reason == "RESERVATION_EXPIRED" and r.data.payment_voided


def test_expired_then_declined_needs_no_compensation() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.send(S.ReservationExpired(r.data.reservation_id))
    r.send(S.PaymentDeclined(r.data.payment_id or "", "INSUFFICIENT_FUNDS"))
    assert r.state is W.CANCELLED


def test_late_payment_authorized_while_cancelling_sends_void() -> None:
    """Rule 3: a PaymentAuthorized that arrives while CANCELLING is recorded and voided."""
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.deadline_fires()
    r.deadline_fires()  # CANCELLING with VOID + RELEASE pending
    r.send(S.PaymentDeclined(r.data.payment_id or "", "PSP_TIMEOUT"))  # payment-svc gave up
    assert S.Compensation.VOID_PAYMENT not in r.data.pending
    d = r.authorized()
    assert [c.name for c in d.commands] == ["VoidPayment"] and S.Compensation.VOID_PAYMENT in r.data.pending
    r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.state is W.CANCELLING
    r.send(S.PaymentVoided(r.data.payment_id or ""))
    assert r.state is W.CANCELLED


def test_duplicate_payment_authorized_is_ignored() -> None:
    r = Run.started().to(W.COMMITTING_STOCK)
    assert r.authorized().ignored
    assert r.cmd_names().count("CommitReservation") == 1


# ----------------------------------------------------------------------------- COMMITTING_STOCK
def test_commit_answer_expired_cancels_with_void() -> None:
    r = Run.started().to(W.COMMITTING_STOCK)
    d = r.send(S.ReservationExpired(r.data.reservation_id))
    assert r.state is W.CANCELLING and [c.name for c in d.commands] == ["VoidPayment"]
    r.send(S.PaymentVoided(r.data.payment_id or ""))
    assert r.state is W.CANCELLED and r.data.cancel_reason == "RESERVATION_EXPIRED"


def test_commit_deadline_resends() -> None:
    r = Run.started().to(W.COMMITTING_STOCK)
    r.deadline_fires()
    r.deadline_fires()
    assert r.cmd_names().count("CommitReservation") == 3 and r.state is W.COMMITTING_STOCK


# ---------------------------------------------------------------------- AWAITING_FULFILMENT_ACK
def test_fulfilment_resends_three_times_then_needs_attention() -> None:
    r = Run.started().to(W.AWAITING_FULFILMENT_ACK)
    for attempt in (2, 3, 4):
        d = r.deadline_fires()
        assert d.commands[0].params["attempt"] == attempt
    d = r.deadline_fires()
    assert r.state is W.NEEDS_ATTENTION and d.outcome == "MANUAL_REVIEW"
    assert [e.name for e in d.events] == ["OrderRequiresAttention"]
    assert r.cmd_names().count("RequestFulfilment") == 4


def test_operator_retry_from_attention_resends_fulfilment() -> None:
    r = Run.started().to(W.AWAITING_FULFILMENT_ACK)
    for _ in range(4):
        r.deadline_fires()
    d = r.send(S.OperatorRetry())
    assert r.state is W.AWAITING_FULFILMENT_ACK and d.commands[0].name == "RequestFulfilment"
    assert d.commands[0].params["attempt"] == 5 and r.attempts == 0
    r.accepted()
    assert r.state is W.FULFILLING


def test_late_acceptance_while_in_attention_moves_on() -> None:
    r = Run.started().to(W.AWAITING_FULFILMENT_ACK)
    for _ in range(4):
        r.deadline_fires()
    r.accepted()
    assert r.state is W.FULFILLING


def test_fulfilment_failed_compensates_release_and_void() -> None:
    for target in (W.AWAITING_FULFILMENT_ACK, W.FULFILLING, W.PACKED):
        r = Run.started().to(target)
        d = r.send(S.FulfilmentFailed(r.data.fulfilment_id or "", "STOCK_DAMAGED"))
        assert r.state is W.CANCELLING, target
        assert sorted(c.name for c in d.commands) == ["ReleaseReservation", "VoidPayment"]
        r.send(S.ReservationReleased(r.data.reservation_id))
        r.send(S.PaymentVoided(r.data.payment_id or ""))
        assert r.state is W.CANCELLED and r.data.cancel_reason == "FULFILMENT_FAILED"
        assert r.events[-1].name == "OrderCancelled"


def test_packed_before_accepted_implies_acceptance() -> None:
    r = Run.started().to(W.AWAITING_FULFILMENT_ACK)
    r.packed()
    assert r.state is W.PACKED and not r.data.early


def test_dispatched_before_packed_is_applied_when_packed() -> None:
    r = Run.started().to(W.FULFILLING)
    r.dispatched()
    assert r.state is W.FULFILLING and len(r.data.early) == 1
    d = r.packed()
    assert r.state is W.CAPTURING and [c.name for c in d.commands] == ["CapturePayment"] and not r.data.early


def test_duplicate_acceptance_and_packing_are_ignored() -> None:
    r = Run.started().to(W.FULFILLING)
    assert r.accepted().ignored
    r.packed()
    assert r.packed().ignored


def test_fulfilling_and_packed_deadlines_need_attention() -> None:
    for target in (W.FULFILLING, W.PACKED):
        r = Run.started().to(target)
        d = r.deadline_fires()
        assert r.state is W.NEEDS_ATTENTION and d.outcome == "MANUAL_REVIEW"


# --------------------------------------------------------------------- CAPTURING (past the pivot)
def test_capture_retryable_failure_backs_off_and_resends() -> None:
    r = Run.started().to(W.CAPTURING)
    d = r.send(S.PaymentCaptureFailed(r.data.payment_id or "", "PSP_ERROR", True))
    assert r.state is W.CAPTURING and not d.commands and r.deadline == r.now + timedelta(minutes=1)
    d = r.deadline_fires()
    assert [c.name for c in d.commands] == ["CapturePayment"] and d.commands[0].params["attempt"] == 2
    r.captured()
    assert r.state is W.SHIPPED


def test_capture_non_retryable_needs_attention_and_never_compensates() -> None:
    """Architecture §5.9 / ADR-0015."""
    r = Run.started().to(W.CAPTURING)
    d = r.send(S.PaymentCaptureFailed(r.data.payment_id or "", "AUTHORIZATION_EXPIRED", False))
    assert r.state is W.NEEDS_ATTENTION and [e.name for e in d.events] == ["OrderRequiresAttention"]
    assert "VoidPayment" not in r.cmd_names() and "ReleaseReservation" not in r.cmd_names()
    d = r.send(S.OperatorRetry())
    assert r.state is W.CAPTURING and d.commands[0].name == "CapturePayment"


def test_capture_deadline_resends() -> None:
    r = Run.started().to(W.CAPTURING)
    r.deadline_fires()
    assert r.cmd_names().count("CapturePayment") == 2


def test_fulfilment_failed_after_pivot_is_ignored() -> None:
    r = Run.started().to(W.CAPTURING)
    assert r.send(S.FulfilmentFailed(r.data.fulfilment_id or "", "STOCK_DAMAGED")).ignored


def test_delivered_before_captured_is_applied_after_capture() -> None:
    """Rule 4: ShipmentDelivered can arrive before PaymentCaptured (different topics)."""
    r = Run.started().to(W.CAPTURING)
    r.delivered()
    assert r.state is W.CAPTURING and r.data.early
    d = r.captured()
    assert r.state is W.DELIVERED and d.outcome == "DELIVERED"
    assert [e.name for e in d.events] == ["InvoiceIssued", "OrderDelivered"]


def test_order_shipped_waits_for_tracking_number() -> None:
    r = Run.started().to(W.CAPTURING)
    d = r.captured()
    assert [e.name for e in d.events] == ["InvoiceIssued"]
    d = r.send(S.ShipmentCreated("ship-1", "fake-carrier", "FC1", True))
    assert [e.name for e in d.events] == ["OrderShipped"]
    assert r.send(S.ShipmentCreated("ship-1", "fake-carrier", "FC1", True)).ignored


# ------------------------------------------------------------------------------------- SHIPPED
def test_lost_parcel_needs_attention_other_exceptions_recorded() -> None:
    r = Run.started().to(W.SHIPPED)
    d = r.send(S.ShipmentException("ship-1", "DELAYED"))
    assert r.state is W.SHIPPED and not d.events
    d = r.send(S.ShipmentException("ship-1", "LOST"))
    assert r.state is W.NEEDS_ATTENTION and d.outcome == "MANUAL_REVIEW"
    r.delivered()
    assert r.state is W.DELIVERED, "parcel found: the facts win"


def test_shipped_deadline_needs_attention() -> None:
    r = Run.started().to(W.SHIPPED)
    r.deadline_fires()
    assert r.state is W.NEEDS_ATTENTION


def test_return_shipments_do_not_move_the_order_saga() -> None:
    r = Run.started().to(W.SHIPPED)
    assert r.send(S.ShipmentDelivered("ret-ship", "2026-12-01T00:00:00+00:00", outbound=False)).ignored


# ----------------------------------------------------------------------------------- CANCELLING
def test_cancelling_deadline_resends_outstanding_forever_with_backoff_and_alerts_once() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.deadline_fires()
    r.deadline_fires()
    r.send(S.ReservationReleased(r.data.reservation_id))
    gaps = []
    alerts = 0
    for _ in range(12):
        d = r.deadline_fires()
        assert [c.name for c in d.commands] == ["VoidPayment"], "only outstanding compensations are resent"
        gaps.append((r.deadline - r.now).total_seconds() if r.deadline else 0)
        alerts += sum(1 for e in d.events if e.name == "OrderRequiresAttention")
    assert r.state is W.CANCELLING and alerts == 1
    assert gaps[0] < gaps[-1] <= 16 * CFG.compensation.total_seconds() + 1


def test_cancelling_reply_keeps_the_deadline() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.deadline_fires()
    r.deadline_fires()
    dl = r.deadline
    r.send(S.ReservationReleased(r.data.reservation_id))
    assert r.deadline == dl, "a partial reply must not clear the compensation deadline"


# ----------------------------------------------------------------------------------- terminal
@pytest.mark.parametrize("terminal", [W.DELIVERED, W.CANCELLED])
def test_terminal_states_ignore_late_replies(terminal: S.State) -> None:
    r = Run.started()
    if terminal is W.DELIVERED:
        r.to(W.DELIVERED)
    else:
        r.send(S.StockReservationRejected(r.data.reservation_id))
    for t in (S.Deadline(), S.OperatorRetry(), S.ReservationCommitted(r.data.reservation_id),
              S.FulfilmentAccepted("x"), S.ShipmentDelivered("s", "2026-11-20T00:00:00+00:00")):
        assert r.send(t).ignored


def test_late_authorization_after_cancelled_is_voided() -> None:
    r = Run.started().to(W.AUTHORIZING_PAYMENT)
    r.send(S.ReservationExpired(r.data.reservation_id))
    r.send(S.PaymentDeclined(r.data.payment_id or "", "PSP_TIMEOUT"))
    assert r.state is W.CANCELLED
    d = r.authorized()
    assert r.state is W.CANCELLED and [c.name for c in d.commands] == ["VoidPayment"]
    

def test_duplicate_checkout_submitted_is_ignored() -> None:
    from .sagahelp import CHECKOUT

    r = Run.started()
    assert r.send(CHECKOUT).ignored


def test_customer_status_mapping() -> None:
    assert S.customer_status(W.AUTHORIZING_PAYMENT) == "PENDING"
    assert S.customer_status(W.PACKED) == "CONFIRMED"
    assert S.customer_status(W.CANCELLING) == "CANCELLED"
    assert S.customer_status(W.NEEDS_ATTENTION) == "NEEDS_ATTENTION"


def test_saga_data_round_trips_through_json() -> None:
    import json

    r = Run.started().to(W.CAPTURING)
    r.delivered()
    again = S.SagaData.from_json(json.loads(json.dumps(r.data.to_json())))
    assert again == r.data
