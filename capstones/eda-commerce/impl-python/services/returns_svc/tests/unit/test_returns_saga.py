"""Every row of the returns saga table (architecture §6.1), late/duplicate/out-of-order replies, and a
property test over random interleavings."""

from __future__ import annotations

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st
from returns_svc.domain import saga as S
from returns_svc.domain.policy import Inspected

from .sagahelp import started

LABEL = {"bucket": "shipping-labels", "objectKey": "k", "contentType": "application/pdf", "sizeBytes": 1, "sha256": "0" * 64}


def ok(q: int = 2) -> S.ParcelInspected:
    return S.ParcelInspected((Inspected("l-1", "SKU-1001", q, "RESTOCKABLE"),))


def to_settling(r: S.Decision | None = None, **kw: object) -> object:
    run = started(**kw)
    run.send(S.LabelCreated(run.data.shipment_id or "", LABEL))
    run.send(S.ParcelReceived())
    run.send(ok())
    return run


def test_auto_approve_runs_requested_authorized_awaiting_parcel_with_both_commands() -> None:
    r = started()
    assert r.path == ["REQUESTED", "AUTHORIZED", "AWAITING_PARCEL"]
    assert r.events == ["ReturnRequested", "ReturnAuthorized"]
    assert r.commands == ["IssueReturnLabel", "ExpectReturn"]
    assert r.data.rma_number == "RMA-2026-000042" and r.data.shipment_id
    assert r.deadline == r.now + S.LABEL_TIMEOUT  # label first, then parcel due date


def test_above_limit_waits_in_manual_review_then_approve_or_reject() -> None:
    r = started(qty=4, unit=20000)  # 800.00 EUR > 500.00
    assert r.state is S.State.MANUAL_REVIEW and r.outcomes == ["MANUAL_REVIEW"] and r.deadline is None
    assert r.send(S.Decide("RETRY_REFUND")).ignored, "only APPROVE/REJECT here"
    r.send(S.Decide("APPROVE", "ok"))
    assert r.state is S.State.AWAITING_PARCEL and r.commands == ["IssueReturnLabel", "ExpectReturn"]
    r2 = started(qty=4, unit=20000)
    r2.send(S.Decide("REJECT", "worn"))
    assert r2.state is S.State.CLOSED and r2.events[-2:] == ["ReturnRejected", "ReturnClosed"]
    assert r2.data.outcome == "REJECTED" and not S.counts_against_order(r2.state, r2.data), "quantity is returnable again"


def test_label_created_is_stored_once_and_resent_on_label_deadline() -> None:
    r = started()
    r.send(S.Deadline(), advance=S.LABEL_TIMEOUT)
    assert r.commands[-2:] == ["IssueReturnLabel", "ExpectReturn"] and r.data.label_resends == 1
    sid = r.data.shipment_id
    r.send(S.LabelCreated("other", LABEL))
    assert r.data.label is None, "matched by shipmentId"
    r.send(S.LabelCreated(sid or "", LABEL))
    assert r.data.label == LABEL and r.deadline is not None and r.deadline.isoformat() == r.data.parcel_due_by
    assert r.send(S.LabelCreated(sid or "", LABEL)).ignored
    note = r.send(S.LabelFailed(sid or "", "BOOKING_FAILED"))
    assert not note.ignored and r.state is S.State.AWAITING_PARCEL


def test_parcel_deadline_expires_and_closes() -> None:
    r = started()
    r.send(S.LabelCreated(r.data.shipment_id or "", LABEL))
    r.send(S.Deadline(), advance=timedelta(days=14))
    assert r.path[-2:] == ["EXPIRED", "CLOSED"] and r.events[-1] == "ReturnClosed" and r.data.outcome == "EXPIRED"
    assert r.outcomes == ["EXPIRED"] and not S.counts_against_order(r.state, r.data)
    assert r.send(S.ParcelReceived()).ignored, "late parcel after close is recorded, not applied"


def test_full_refund_path_closes_refunded_after_both_replies_in_any_order() -> None:
    for first, second in ((S.Restocked, S.RefundSucceeded), (S.RefundSucceeded, S.Restocked)):
        r = to_settling()
        assert r.state is S.State.SETTLING and r.commands[-2:] == ["RestockItems", "RefundPayment"]
        assert r.data.refund_minor == 25998 and r.data.restock_lines == (("SKU-1001", 2),)
        ids = {S.Restocked: r.data.restock_id, S.RefundSucceeded: r.data.refund_id}
        r.send(first(ids[first] or ""))
        assert r.state is S.State.SETTLING
        r.send(first(ids[first] or ""))  # duplicate reply: ignored
        r.send(second(ids[second] or ""))
        assert r.state is S.State.CLOSED and r.data.outcome == "REFUNDED"
        assert r.events[-2:] == ["ReturnRefunded", "ReturnClosed"] and r.outcomes == ["REFUNDED"]


def test_damaged_with_changed_mind_is_partially_refunded_and_not_restocked() -> None:
    r = started()
    r.send(S.ParcelReceived())
    r.send(S.ParcelInspected((Inspected("l-1", "SKU-1001", 1, "RESTOCKABLE"), Inspected("l-1", "SKU-1001", 1, "DAMAGED"))))
    assert r.data.refund_minor == 12999 and r.data.restock_lines == (("SKU-1001", 1),)
    r.send(S.Restocked(r.data.restock_id or ""))
    r.send(S.RefundSucceeded(r.data.refund_id or ""))
    assert r.data.outcome == "PARTIALLY_REFUNDED"


def test_nothing_refundable_is_rejected_after_inspection() -> None:
    r = started()
    r.send(S.ParcelReceived())
    r.send(S.ParcelInspected((Inspected("l-1", "SKU-1001", 2, "DAMAGED"),)))
    assert r.path[-2:] == ["REJECTED", "CLOSED"] and r.data.outcome == "REJECTED"
    assert "RefundPayment" not in r.commands and "RestockItems" not in r.commands
    assert S.counts_against_order(r.state, r.data), "the items came back: not returnable again"


def test_inspection_before_received_implies_receipt() -> None:
    r = started()
    r.send(ok())
    assert r.state is S.State.SETTLING and r.data.received


def test_refund_retry_schedule_then_refund_review_and_retry_refund_with_same_id() -> None:
    r = to_settling()
    rid = r.data.refund_id
    r.send(S.Restocked(r.data.restock_id or ""))
    for wait in S.REFUND_RETRY_SCHEDULE:
        r.send(S.RefundFailed(rid or "", retryable=True, reason="processing_error"))
        assert r.state is S.State.SETTLING and r.deadline == r.now + wait
        assert r.send(S.Deadline(), advance=wait - timedelta(seconds=1)).ignored, "not before the schedule"
        r.send(S.Deadline(), advance=timedelta(seconds=1))
        assert r.commands[-1] == "RefundPayment"
    r.send(S.RefundFailed(rid or "", retryable=True))
    assert r.state is S.State.REFUND_REVIEW and r.outcomes == ["MANUAL_REVIEW"] and r.deadline is None
    r.send(S.Decide("RETRY_REFUND"))
    assert r.state is S.State.SETTLING and r.commands[-1] == "RefundPayment" and r.data.refund_id == rid
    r.send(S.RefundSucceeded(rid or ""))
    assert r.data.outcome == "REFUNDED"


def test_non_retryable_refund_failure_and_close_without_refund() -> None:
    r = to_settling()
    r.send(S.RefundFailed(r.data.refund_id or "", retryable=False, reason="not_captured"))
    assert r.state is S.State.REFUND_REVIEW
    r.send(S.Restocked(r.data.restock_id or ""))
    assert r.data.restock_done
    r.send(S.Decide("CLOSE_WITHOUT_REFUND", "goodwill voucher"))
    assert r.state is S.State.CLOSED and r.data.outcome == "MANUAL_REVIEW" and r.events[-1] == "ReturnClosed"
    assert S.api_status(r.state, r.data) == "REJECTED"


def test_late_success_in_refund_review_settles_forward() -> None:
    r = to_settling()
    r.send(S.Restocked(r.data.restock_id or ""))
    r.send(S.RefundFailed(r.data.refund_id or "", retryable=False))
    r.send(S.RefundSucceeded(r.data.refund_id or ""))
    assert r.state is S.State.CLOSED and r.data.outcome == "REFUNDED"


def test_missing_replies_are_resent_on_deadline() -> None:
    r = to_settling()
    r.send(S.Deadline(), advance=S.RESTOCK_TIMEOUT)
    assert r.commands[-1] == "RestockItems"
    r.send(S.Deadline(), advance=S.REFUND_REPLY_TIMEOUT)
    assert "RefundPayment" in r.commands[-2:]


def test_replies_for_other_ids_are_ignored_and_closed_saga_ignores_everything() -> None:
    r = to_settling()
    assert r.send(S.RefundSucceeded("someone-else")).ignored
    assert r.send(S.Restocked("other")).ignored
    r.send(S.Restocked(r.data.restock_id or ""))
    r.send(S.RefundSucceeded(r.data.refund_id or ""))
    for t in (S.RefundSucceeded(r.data.refund_id or ""), S.Deadline(), S.Decide("APPROVE"), ok()):
        assert r.send(t).ignored


def test_operator_retry_resends_current_step() -> None:
    r = started()
    r.send(S.LabelCreated(r.data.shipment_id or "", LABEL))
    r.send(S.OperatorRetry())
    assert r.commands[-2:] == ["IssueReturnLabel", "ExpectReturn"]
    r2 = to_settling()
    r2.send(S.OperatorRetry())
    assert sorted(r2.commands[-2:]) == ["RefundPayment", "RestockItems"]


def test_api_status_mapping() -> None:
    d = started().data
    assert S.api_status(S.State.AWAITING_INSPECTION, d) == "RECEIVED"
    assert S.api_status(S.State.SETTLING, d) == "REFUNDING"
    assert S.api_status(S.State.REFUND_REVIEW, d) == "MANUAL_REVIEW"


REPLIES = st.lists(
    st.sampled_from(
        [
            "label",
            "received",
            "inspected_ok",
            "inspected_mixed",
            "restocked",
            "refund_ok",
            "refund_fail",
            "refund_fatal",
            "deadline",
            "dup",
        ]
    ),
    max_size=25,
)


@settings(max_examples=300, deadline=None)
@given(REPLIES, st.booleans())
def test_random_interleavings_end_closed_or_waiting_with_consistent_effects(steps: list[str], big: bool) -> None:
    r = started(qty=4, unit=20000) if big else started()
    if big:
        r.send(S.Decide("APPROVE"))
    last: S.Trigger | None = None
    for s in steps:
        d = r.data
        t: S.Trigger = {
            "label": S.LabelCreated(d.shipment_id or "", LABEL),
            "received": S.ParcelReceived(),
            "inspected_ok": ok(4 if big else 2),
            "inspected_mixed": S.ParcelInspected(
                (Inspected("l-1", "SKU-1001", 1, "RESTOCKABLE"), Inspected("l-1", "SKU-1001", 1, "MISSING"))
            ),
            "restocked": S.Restocked(d.restock_id or "x"),
            "refund_ok": S.RefundSucceeded(d.refund_id or "x"),
            "refund_fail": S.RefundFailed(d.refund_id or "x", retryable=True),
            "refund_fatal": S.RefundFailed(d.refund_id or "x", retryable=False),
            "deadline": S.Deadline(),
            "dup": last or S.Deadline(),
        }[s]
        r.send(t, advance=timedelta(hours=2))
        last = t
    d = r.data
    # Invariants: one refund id for the whole saga; never refund more than the value of the return;
    # a refund only after inspection; closed means every outstanding step was confirmed or a human decided.
    assert d.refund_minor <= d.value_minor + d.shipping_fee_minor
    if r.commands.count("RefundPayment"):
        assert d.refund_id and d.results
    assert r.events.count("ReturnClosed") <= 1 and r.events.count("ReturnRefunded") <= 1
    if r.state is S.State.CLOSED:
        assert d.outcome is not None
        if d.outcome in ("REFUNDED", "PARTIALLY_REFUNDED"):
            assert d.refund_done and d.restock_done
    else:
        assert r.state in (
            S.State.AWAITING_PARCEL,
            S.State.AWAITING_INSPECTION,
            S.State.SETTLING,
            S.State.REFUND_REVIEW,
            S.State.REJECTED,
        )
    assert r.events[0] == "ReturnRequested"
