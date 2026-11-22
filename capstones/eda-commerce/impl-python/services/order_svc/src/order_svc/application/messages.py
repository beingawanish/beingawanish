"""Domain decisions -> outgoing Avro bodies (guide §3 ``messages.py``).

The saga kit assigns envelopes and aggregate versions; this module only knows topics, record types
and field names from the contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts_py import records as R
from edacommon.saga import PendingMessage

from order_svc.application.ports import OrderRecord
from order_svc.domain import saga as S


def _money(minor: int, currency: str) -> dict[str, Any]:
    return {"amountMinor": minor, "currency": currency}


def _pm(
    cls: Any, key: str, body: dict[str, Any], *, event: bool, aggregate_type: str = "Order", aggregate_id: str | None = None
) -> PendingMessage:
    return PendingMessage(
        topic=cls.TOPIC,
        record_type=cls.AVRO_NAME,
        key=key,
        body=body,
        aggregate_type=aggregate_type,
        is_event=event,
        aggregate_id=aggregate_id,
    )


def command(c: S.Command, d: S.SagaData, order: OrderRecord) -> PendingMessage:
    oid = d.order_id
    if c.name == "ReserveStock":
        return _pm(
            R.ReserveStock,
            oid,
            {
                "orderId": oid,
                "reservationId": c.business_id,
                "ttlSeconds": int(c.params.get("ttlSeconds", 900)),
                "lines": [{"sku": x.sku, "quantity": x.quantity} for x in d.lines],
            },
            event=False,
            aggregate_type="Order",
            aggregate_id=oid,
        )
    if c.name == "AuthorizePayment":
        return _pm(
            R.AuthorizePayment,
            oid,
            {
                "orderId": oid,
                "paymentId": c.business_id,
                "customerId": d.customer_id,
                "amount": _money(d.total_minor, d.currency),
                "paymentMethodToken": d.payment_token,
            },
            event=False,
            aggregate_id=oid,
        )
    if c.name == "CommitReservation":
        return _pm(R.CommitReservation, oid, {"orderId": oid, "reservationId": c.business_id}, event=False, aggregate_id=oid)
    if c.name == "ReleaseReservation":
        return _pm(
            R.ReleaseReservation,
            oid,
            {"orderId": oid, "reservationId": c.business_id, "reason": str(c.params.get("reason", "CANCELLED"))},
            event=False,
            aggregate_id=oid,
        )
    if c.name == "VoidPayment":
        return _pm(
            R.VoidPayment,
            oid,
            {"orderId": oid, "paymentId": c.business_id, "reason": str(c.params.get("reason", "CANCELLED"))},
            event=False,
            aggregate_id=oid,
        )
    if c.name == "RequestFulfilment":
        return _pm(
            R.RequestFulfilment,
            oid,
            {
                "orderId": oid,
                "fulfilmentId": c.business_id,
                "lines": list(order.lines),
                "shipTo": order.ship_to,
                "shippingMethod": order.shipping_method,
                "attempt": int(c.params.get("attempt", 1)),
            },
            event=False,
            aggregate_id=oid,
        )
    if c.name == "CancelFulfilment":
        return _pm(
            R.CancelFulfilment,
            oid,
            {"orderId": oid, "fulfilmentId": c.business_id, "reason": str(c.params.get("reason", "CANCELLED"))},
            event=False,
            aggregate_id=oid,
        )
    if c.name == "CapturePayment":
        return _pm(
            R.CapturePayment,
            oid,
            {"orderId": oid, "paymentId": c.business_id, "amount": _money(d.total_minor, d.currency)},
            event=False,
            aggregate_id=oid,
        )
    raise ValueError(f"unknown command {c.name}")


def event(
    e: S.Event, d: S.SagaData, order: OrderRecord, state: S.State, now: datetime, invoice: dict[str, Any] | None = None
) -> PendingMessage:
    oid = d.order_id
    if e.name == "OrderPlaced":
        return _pm(
            R.OrderPlaced,
            oid,
            {
                "orderId": oid,
                "customerId": d.customer_id,
                "lines": list(order.lines),
                "total": _money(d.total_minor, d.currency),
                "shippingAddress": order.ship_to,
                "contactEmail": order.contact_email,
                "shippingMethod": order.shipping_method,
                "placedAt": order.placed_at,
            },
            event=True,
        )
    if e.name == "OrderConfirmed":
        return _pm(
            R.OrderConfirmed,
            oid,
            {
                "orderId": oid,
                "reservationId": d.reservation_id,
                "paymentId": d.payment_id,
                "fulfilmentId": d.fulfilment_id,
                "confirmedAt": now,
            },
            event=True,
        )
    if e.name == "OrderCancelled":
        reason = R.CancellationReason.parse(d.cancel_reason or "UNKNOWN").value
        return _pm(
            R.OrderCancelled,
            oid,
            {"orderId": oid, "reason": reason, "detail": d.cancel_detail, "paymentVoided": d.payment_voided, "cancelledAt": now},
            event=True,
        )
    if e.name == "OrderShipped":
        return _pm(
            R.OrderShipped,
            oid,
            {
                "orderId": oid,
                "shipmentId": d.shipment_id or "",
                "carrier": d.carrier or "",
                "trackingNumber": d.tracking_number or "",
                "capturedAmount": _money(d.total_minor, d.currency),
                "shippedAt": now,
            },
            event=True,
        )
    if e.name == "OrderDelivered":
        delivered = datetime.fromisoformat(str(e.params["deliveredAt"]))
        return _pm(
            R.OrderDelivered,
            oid,
            {
                "orderId": oid,
                "shipmentId": d.shipment_id or "",
                "deliveredAt": delivered,
                "returnWindowEndsAt": delivered + S.RETURN_WINDOW,
            },
            event=True,
        )
    if e.name == "OrderRequiresAttention":
        return _pm(
            R.OrderRequiresAttention,
            oid,
            {
                "orderId": oid,
                "sagaState": str(e.params.get("state", state.value)),
                "issue": str(e.params.get("issue", "")),
                "raisedAt": now,
            },
            event=True,
        )
    if e.name == "InvoiceIssued":
        assert invoice is not None
        return _pm(
            R.InvoiceIssued,
            oid,
            {
                "orderId": oid,
                "invoiceId": invoice["invoiceId"],
                "invoiceNumber": invoice["invoiceNumber"],
                "total": _money(d.total_minor, d.currency),
                "document": invoice["document"],
                "issuedAt": invoice["issuedAt"],
            },
            event=True,
        )
    raise ValueError(f"unknown event {e.name}")
