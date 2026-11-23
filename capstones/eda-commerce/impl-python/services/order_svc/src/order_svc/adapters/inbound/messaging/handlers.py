"""order-svc's saga consumers: every reply on the participants' event topics becomes a domain
trigger. This module is the translation layer between contract records and saga triggers; enum
values the saga does not know (``UNKNOWN``) are passed through as text, never raised on."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from order_svc.application.handle_saga_trigger import OrderSaga
from order_svc.application.ports import OrderRecord
from order_svc.domain import saga as S

TOPICS = [
    R.CheckoutSubmitted.TOPIC,
    R.StockReserved.TOPIC,
    R.PaymentAuthorized.TOPIC,
    R.FulfilmentAccepted.TOPIC,
    R.ShipmentCreated.TOPIC,
]


def _iso(v: Any) -> str | None:
    return v.isoformat() if v is not None else None


def checkout_trigger(m: R.CheckoutSubmitted) -> tuple[S.CheckoutSubmitted, OrderRecord]:
    lines = tuple(
        S.Line(x.line_id, x.sku, x.product_name, x.quantity, x.unit_price.amount_minor, x.line_total.amount_minor)
        for x in m.lines
    )
    ship_to = m.shipping_address.to_avro()
    t = S.CheckoutSubmitted(
        order_id=m.order_id,
        customer_id=m.customer_id,
        currency=m.total.currency,
        total_minor=m.total.amount_minor,
        lines=lines,
        ship_to=ship_to,
        shipping_method=m.shipping_method.value,
        payment_token=m.payment_method_token,
    )
    order = OrderRecord(
        order_id=m.order_id,
        customer_id=m.customer_id,
        status="PENDING",
        total_minor=m.total.amount_minor,
        currency=m.total.currency,
        placed_at=m.envelope.occurred_at,
        version=0,
        contact_email=m.contact_email,
        ship_to=ship_to,
        shipping_method=m.shipping_method.value,
        lines=tuple(x.to_avro() for x in m.lines),
    )
    return t, order


# record type -> function(record) -> (orderId, trigger)
TRANSLATE: dict[type[Any], Callable[[Any], tuple[str, S.Trigger]]] = {
    R.StockReserved: lambda m: (m.order_id, S.StockReserved(m.reservation_id)),
    R.StockReservationRejected: lambda m: (
        m.order_id,
        S.StockReservationRejected(m.reservation_id, ", ".join(f"{s.sku} {s.available}/{s.requested}" for s in m.shortages)),
    ),
    R.ReservationCommitted: lambda m: (m.order_id, S.ReservationCommitted(m.reservation_id)),
    R.ReservationReleased: lambda m: (m.order_id, S.ReservationReleased(m.reservation_id)),
    R.ReservationExpired: lambda m: (m.order_id, S.ReservationExpired(m.reservation_id)),
    R.PaymentAuthorized: lambda m: (m.order_id, S.PaymentAuthorized(m.payment_id, _iso(m.authorization_expires_at))),
    R.PaymentDeclined: lambda m: (m.order_id, S.PaymentDeclined(m.payment_id, m.reason.value)),
    R.PaymentCaptured: lambda m: (m.order_id, S.PaymentCaptured(m.payment_id, m.amount.amount_minor)),
    R.PaymentCaptureFailed: lambda m: (m.order_id, S.PaymentCaptureFailed(m.payment_id, m.reason.value, m.retryable)),
    R.PaymentVoided: lambda m: (m.order_id, S.PaymentVoided(m.payment_id)),
    R.FulfilmentAccepted: lambda m: (m.order_id, S.FulfilmentAccepted(m.fulfilment_id)),
    R.OrderPacked: lambda m: (m.order_id, S.OrderPacked(m.fulfilment_id)),
    R.OrderDispatched: lambda m: (m.order_id, S.OrderDispatched(m.fulfilment_id, m.shipment_id)),
    R.FulfilmentFailed: lambda m: (m.order_id, S.FulfilmentFailed(m.fulfilment_id, m.reason.value)),
    R.FulfilmentCancelled: lambda m: (m.order_id, S.FulfilmentCancelled(m.fulfilment_id)),
    R.ShipmentCreated: lambda m: (
        m.order_id,
        S.ShipmentCreated(m.shipment_id, m.carrier, m.tracking_number, m.direction is R.ShipmentDirection.OUTBOUND),
    ),
    R.ShipmentDelivered: lambda m: (
        m.order_id,
        S.ShipmentDelivered(m.shipment_id, m.delivered_at.isoformat(), m.direction is R.ShipmentDirection.OUTBOUND),
    ),
    R.ShipmentException: lambda m: (
        m.order_id,
        S.ShipmentException(m.shipment_id, m.code.value, m.direction is R.ShipmentDirection.OUTBOUND),
    ),
}
# Received but irrelevant to the saga (OrderPicked, ItemsRestocked, ShipmentInTransit, returns
# events, refunds) are simply not registered: the runtime counts them as "ignored".


def build_registry(saga_for: Callable[[UnitOfWork], OrderSaga], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(R.CheckoutSubmitted)
    def on_checkout(m: R.CheckoutSubmitted, ctx: MessageContext, uow: UnitOfWork) -> None:
        t, order = checkout_trigger(m)
        saga_for(uow).start(uow, t, order, trigger_id=ctx.event_id)

    def make(translate: Callable[[Any], tuple[str, S.Trigger]]) -> Callable[[Any, MessageContext, UnitOfWork], None]:
        def handle(m: Any, ctx: MessageContext, uow: UnitOfWork) -> None:
            order_id, trigger = translate(m)
            saga_for(uow).on_trigger(uow, order_id, trigger, trigger_type=ctx.event_type, trigger_id=ctx.event_id)

        return handle

    for cls, fn in TRANSLATE.items():
        reg.register(cls, make(fn))
    return reg
