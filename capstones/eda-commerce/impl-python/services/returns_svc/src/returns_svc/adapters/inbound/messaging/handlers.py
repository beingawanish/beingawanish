"""returns-svc consumers: order events feed the eligibility view; participants' replies become saga
triggers. Enum values the saga does not know (``UNKNOWN``) are passed through as text, never raised on."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from returns_svc.application.returns import ReturnsSaga
from returns_svc.domain import saga as S
from returns_svc.domain.policy import Inspected, OrderLine

TOPICS = [R.OrderPlaced.TOPIC, R.RefundSucceeded.TOPIC, R.ItemsRestocked.TOPIC, R.ReturnReceived.TOPIC, R.ShipmentCreated.TOPIC]


def build_registry(saga_for: Callable[[UnitOfWork], ReturnsSaga], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    # ---------------------------------------------------------------- eligibility view (ADR-0010)
    @reg.handler(R.OrderPlaced)
    def on_placed(m: R.OrderPlaced, ctx: MessageContext, uow: UnitOfWork) -> None:
        lines = tuple(
            OrderLine(x.line_id, x.sku, x.product_name, x.quantity, x.unit_price.amount_minor, x.line_total.amount_minor)
            for x in m.lines
        )
        saga_for(uow).on_order_placed(
            uow,
            order_id=m.order_id,
            customer_id=m.customer_id,
            currency=m.total.currency,
            total_minor=m.total.amount_minor,
            lines=lines,
            ship_to=m.shipping_address.to_avro(),
            now=clock.now(),
        )

    @reg.handler(R.OrderConfirmed)
    def on_confirmed(m: R.OrderConfirmed, ctx: MessageContext, uow: UnitOfWork) -> None:
        saga_for(uow).on_order_fact(uow, m.order_id, clock.now(), payment_id=m.payment_id)

    @reg.handler(R.OrderDelivered)
    def on_delivered(m: R.OrderDelivered, ctx: MessageContext, uow: UnitOfWork) -> None:
        saga_for(uow).on_order_fact(uow, m.order_id, clock.now(), delivered_at=m.delivered_at)

    @reg.handler(R.OrderCancelled)
    def on_cancelled(m: R.OrderCancelled, ctx: MessageContext, uow: UnitOfWork) -> None:
        saga_for(uow).on_order_fact(uow, m.order_id, clock.now(), cancelled=True)

    @reg.handler(R.FulfilmentAccepted)
    def on_accepted(m: R.FulfilmentAccepted, ctx: MessageContext, uow: UnitOfWork) -> None:
        saga_for(uow).on_order_fact(uow, m.order_id, clock.now(), warehouse_id=m.warehouse_id)

    # ------------------------------------------------------------------------ saga replies
    def trigger(
        fn: Callable[[Any, UnitOfWork], tuple[str, S.Trigger] | None],
    ) -> Callable[[Any, MessageContext, UnitOfWork], None]:
        def handle(m: Any, ctx: MessageContext, uow: UnitOfWork) -> None:
            found = fn(m, uow)
            if found is not None:
                saga_for(uow).on_trigger(uow, found[0], found[1], trigger_type=ctx.event_type, trigger_id=ctx.event_id)

        return handle

    def created(m: R.ShipmentCreated, uow: UnitOfWork) -> tuple[str, S.Trigger] | None:
        if m.direction is not R.ShipmentDirection.RETURN or m.return_id is None:
            return None
        return m.return_id, S.LabelCreated(m.shipment_id, m.label.to_avro())

    def exception(m: R.ShipmentException, uow: UnitOfWork) -> tuple[str, S.Trigger] | None:
        if m.direction is not R.ShipmentDirection.RETURN:
            return None
        rid = saga_id_for_shipment(m.order_id, m.shipment_id, uow)
        return (rid, S.LabelFailed(m.shipment_id, m.code.value)) if rid else None

    def saga_id_for_shipment(order_id: str, shipment_id: str, uow: UnitOfWork) -> str | None:
        from sqlalchemy import text

        row = uow.session.execute(
            text("SELECT saga_id FROM saga_instance WHERE saga_type = 'RETURN' AND data->>'shipment_id' = :s"), {"s": shipment_id}
        ).first()
        return str(row[0]) if row else None

    def refund_return_id(m: Any, uow: UnitOfWork) -> str | None:
        return m.return_id or saga_for(uow).return_id_for_refund(uow, m.refund_id)

    def refunded(m: R.RefundSucceeded, uow: UnitOfWork) -> tuple[str, S.Trigger] | None:
        rid = refund_return_id(m, uow)
        return (rid, S.RefundSucceeded(m.refund_id)) if rid else None

    def refund_failed(m: R.RefundFailed, uow: UnitOfWork) -> tuple[str, S.Trigger] | None:
        rid = refund_return_id(m, uow)
        return (rid, S.RefundFailed(m.refund_id, m.retryable, m.reason)) if rid else None

    def inspected(m: R.ReturnInspected, uow: UnitOfWork) -> tuple[str, S.Trigger] | None:
        results = tuple(Inspected(x.line_id, x.sku, x.quantity, x.outcome.value) for x in m.results)
        return m.return_id, S.ParcelInspected(results)

    reg.register(R.ShipmentCreated, trigger(created))
    reg.register(R.ShipmentException, trigger(exception))
    reg.register(R.ReturnReceived, trigger(lambda m, uow: (m.return_id, S.ParcelReceived())))
    reg.register(R.ReturnInspected, trigger(inspected))
    reg.register(R.ItemsRestocked, trigger(lambda m, uow: (m.return_id, S.Restocked(m.restock_id))))
    reg.register(R.RefundSucceeded, trigger(refunded))
    reg.register(R.RefundFailed, trigger(refund_failed))
    return reg
