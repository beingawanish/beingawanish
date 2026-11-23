"""Saga decisions -> outgoing Avro bodies (returns.events.v1 and the participants' command topics).

Every message is keyed by orderId (topics.yaml: per orderId, which also orders several returns of the
same order); the aggregate is the return.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts_py import records as R
from edacommon.saga import PendingMessage

from returns_svc.domain import saga as S

AGG = "Return"


def _money(minor: int, currency: str) -> dict[str, Any]:
    return {"amountMinor": minor, "currency": currency}


def _pm(cls: Any, d: S.SagaData, body: dict[str, Any], *, event: bool) -> PendingMessage:
    return PendingMessage(
        topic=cls.TOPIC,
        record_type=cls.AVRO_NAME,
        key=d.order_id,
        body={"orderId": d.order_id, "returnId": d.return_id, **body},
        aggregate_type=AGG,
        is_event=event,
        aggregate_id=d.return_id,
    )


def _lines(d: S.SagaData) -> list[dict[str, Any]]:
    return [{"lineId": x.line_id, "sku": x.sku, "quantity": x.quantity} for x in d.lines]


def _ts(v: str | None, now: datetime) -> datetime:
    return datetime.fromisoformat(v) if v else now


def command(c: S.Command, d: S.SagaData, now: datetime) -> PendingMessage:
    if c.name == "IssueReturnLabel":
        assert d.shipment_id
        return _pm(
            R.IssueReturnLabel,
            d,
            {"shipmentId": d.shipment_id, "pickupFrom": d.pickup_from, "toWarehouseId": d.warehouse_id},
            event=False,
        )
    if c.name == "ExpectReturn":
        assert d.rma_number
        return _pm(
            R.ExpectReturn,
            d,
            {"rmaNumber": d.rma_number, "lines": _lines(d), "expectedBy": _ts(d.parcel_due_by, now)},
            event=False,
        )
    if c.name == "RestockItems":
        assert d.restock_id
        return _pm(
            R.RestockItems,
            d,
            {"restockId": d.restock_id, "lines": [{"sku": s, "quantity": q} for s, q in d.restock_lines]},
            event=False,
        )
    if c.name == "RefundPayment":
        assert d.refund_id
        assert d.payment_id, "a delivered order always has a payment"
        body = {
            "paymentId": d.payment_id,
            "refundId": d.refund_id,
            "amount": _money(d.refund_minor, d.currency),
            "reason": f"return {d.rma_number}",
        }
        return _pm(R.RefundPayment, d, body, event=False)
    raise ValueError(f"unknown command {c.name}")


def event(e: S.Event, d: S.SagaData, now: datetime) -> PendingMessage:
    if e.name == "ReturnRequested":
        return _pm(
            R.ReturnRequested,
            d,
            {
                "customerId": d.customer_id,
                "lines": _lines(d),
                "reason": d.reason,
                "requestedAt": _ts(d.requested_at, now),
                "comment": d.comment,
            },
            event=True,
        )
    if e.name == "ReturnAuthorized":
        assert d.rma_number
        return _pm(
            R.ReturnAuthorized,
            d,
            {"rmaNumber": d.rma_number, "authorizedAt": now, "parcelDueBy": _ts(d.parcel_due_by, now)},
            event=True,
        )
    if e.name == "ReturnRejected":
        return _pm(R.ReturnRejected, d, {"reason": d.rejection_reason or "rejected", "rejectedAt": now}, event=True)
    if e.name == "ReturnRefunded":
        assert d.refund_id
        return _pm(
            R.ReturnRefunded,
            d,
            {"refundId": d.refund_id, "amount": _money(d.refund_minor, d.currency), "refundedAt": now},
            event=True,
        )
    if e.name == "ReturnClosed":
        return _pm(R.ReturnClosed, d, {"outcome": d.outcome or "UNKNOWN", "closedAt": now}, event=True)
    raise ValueError(f"unknown event {e.name}")
