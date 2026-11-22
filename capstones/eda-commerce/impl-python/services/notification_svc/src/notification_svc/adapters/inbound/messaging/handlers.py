"""notification-svc consumers: the translation table from contract record to :class:`Notice`.

Adding a reaction is adding one row here (and a template); no producer changes (ADR-0001). Events on
the subscribed topics that need no message (OrderPlaced aside, which feeds the contact store) are
simply not registered and are counted as ``ignored``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from notification_svc.application.notifications import Notifications
from notification_svc.domain.templates import Notice, money

TOPICS = [R.OrderPlaced.TOPIC, R.RefundSucceeded.TOPIC, R.ShipmentCreated.TOPIC, R.ReturnAuthorized.TOPIC]


def _m(x: R.Money) -> str:
    return money(x.amount_minor, x.currency)


def _day(v: Any) -> str:
    return f"{v:%Y-%m-%d}"


# record type -> Notice, or None when this instance of the event needs no message
TRANSLATE: dict[type[Any], Callable[[Any], Notice | None]] = {
    R.OrderConfirmed: lambda m: Notice("order-confirmed.v1", m.order_id, m.order_id),
    R.OrderCancelled: lambda m: Notice(
        "order-cancelled.v1",
        m.order_id,
        m.order_id,
        {
            "reason": m.reason.value.replace("_", " ").lower(),
            "paymentNote": "No money was taken." if not m.payment_voided else "The authorisation on your card was released.",
        },
    ),
    R.OrderShipped: lambda m: Notice(
        "order-shipped.v1", m.order_id, m.order_id, {"carrier": m.carrier, "trackingNumber": m.tracking_number}
    ),
    R.InvoiceIssued: lambda m: Notice(
        "invoice.v1",
        m.invoice_id,
        m.order_id,
        {"invoiceNumber": m.invoice_number, "total": _m(m.total)},
        (m.document.to_avro(),),
    ),
    R.OrderDelivered: lambda m: Notice(
        "order-delivered.v1", m.order_id, m.order_id, {"returnWindowEndsAt": _day(m.return_window_ends_at)}
    ),
    # Refunds that belong to a return are announced by ReturnRefunded instead.
    R.RefundSucceeded: lambda m: (
        None if m.return_id else Notice("refund-issued.v1", m.refund_id, m.order_id, {"amount": _m(m.amount)})
    ),
    R.ShipmentCreated: lambda m: (
        Notice("return-label.v1", m.shipment_id, m.order_id, {"trackingNumber": m.tracking_number}, (m.label.to_avro(),))
        if m.direction is R.ShipmentDirection.RETURN
        else None
    ),
    R.ShipmentException: lambda m: (
        Notice(
            "shipment-problem.v1",
            m.carrier_event_id or f"{m.shipment_id}:{m.code.value}",
            m.order_id,
            {"code": m.code.value.lower()},
        )
        if m.direction is R.ShipmentDirection.OUTBOUND and m.code is not R.ShipmentExceptionCode.BOOKING_FAILED
        else None
    ),
    R.ReturnAuthorized: lambda m: Notice(
        "return-authorized.v1", m.return_id, m.order_id, {"rmaNumber": m.rma_number, "parcelDueBy": _day(m.parcel_due_by)}
    ),
    R.ReturnRejected: lambda m: Notice("return-rejected.v1", m.return_id, m.order_id, {"reason": m.reason}),
    R.ReturnRefunded: lambda m: Notice("return-refunded.v1", m.refund_id, m.order_id, {"amount": _m(m.amount)}),
    R.ReturnClosed: lambda m: (
        Notice("return-expired.v1", m.return_id, m.order_id) if m.outcome is R.ReturnOutcome.EXPIRED else None
    ),
}


def build_registry(notifications_for: Callable[[UnitOfWork], Notifications], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(R.OrderPlaced)
    def on_placed(m: R.OrderPlaced, ctx: MessageContext, uow: UnitOfWork) -> None:
        notifications_for(uow).record_contact(
            order_id=m.order_id,
            customer_id=m.customer_id,
            email=m.contact_email,
            name=m.shipping_address.recipient_name,
            now=clock.now(),
        )

    def make(translate: Callable[[Any], Notice | None]) -> Callable[[Any, MessageContext, UnitOfWork], None]:
        def handle(m: Any, ctx: MessageContext, uow: UnitOfWork) -> None:
            notice = translate(m)
            if notice is not None:
                notifications_for(uow).notify(
                    notice, source_event_id=ctx.event_id, source_event_type=ctx.event_type, now=clock.now()
                )

        return handle

    for cls, fn in TRANSLATE.items():
        reg.register(cls, make(fn))
    return reg
