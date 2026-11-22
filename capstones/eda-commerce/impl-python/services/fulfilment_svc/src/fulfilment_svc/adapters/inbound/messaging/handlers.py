"""fulfilment-svc consumers: commands on fulfilment.commands.v1 and the shipping events this service
choreographs with (ShipmentCreated OUTBOUND -> dispatch, ShipmentDelivered RETURN -> intake)."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock
from edacommon.logging import get_logger

from fulfilment_svc.application.use_cases import Fulfilments
from fulfilment_svc.domain.model import OrderLine, ReturnLine

log = get_logger(__name__)
TOPICS = [R.RequestFulfilment.TOPIC, R.ShipmentCreated.TOPIC]


def build_registry(fulfilments_for: Callable[[UnitOfWork], Fulfilments], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(R.RequestFulfilment)
    def on_request(cmd: R.RequestFulfilment, ctx: MessageContext, uow: UnitOfWork) -> None:
        fulfilments_for(uow).request(
            fulfilment_id=cmd.fulfilment_id,
            order_id=cmd.order_id,
            lines=[OrderLine(x.line_id, x.sku, x.product_name, x.quantity) for x in cmd.lines],
            ship_to=cmd.ship_to.to_avro(),
            shipping_method=cmd.shipping_method.value,
            attempt=cmd.attempt,
            command_id=ctx.event_id,
            correlation_id=ctx.correlation_id,
            now=clock.now(),
        )

    @reg.handler(R.CancelFulfilment)
    def on_cancel(cmd: R.CancelFulfilment, ctx: MessageContext, uow: UnitOfWork) -> None:
        fulfilments_for(uow).cancel(
            fulfilment_id=cmd.fulfilment_id,
            order_id=cmd.order_id,
            reason=cmd.reason,
            correlation_id=ctx.correlation_id,
            now=clock.now(),
        )

    @reg.handler(R.ExpectReturn)
    def on_expect(cmd: R.ExpectReturn, ctx: MessageContext, uow: UnitOfWork) -> None:
        fulfilments_for(uow).expect_return(
            return_id=cmd.return_id,
            order_id=cmd.order_id,
            rma_number=cmd.rma_number,
            lines=[ReturnLine(x.line_id, x.sku, x.quantity) for x in cmd.lines],
            expected_by=cmd.expected_by,
            correlation_id=ctx.correlation_id,
            now=clock.now(),
        )

    @reg.handler(R.ShipmentCreated)
    def on_shipment_created(ev: R.ShipmentCreated, ctx: MessageContext, uow: UnitOfWork) -> None:
        if ev.direction is not R.ShipmentDirection.OUTBOUND:
            return  # return labels are the customer's business until the parcel arrives
        if ev.fulfilment_id is None:
            log.warning("outbound shipment without fulfilmentId; ignored", order_id=ev.order_id)
            return
        fulfilments_for(uow).on_shipment_created(fulfilment_id=ev.fulfilment_id, shipment_id=ev.shipment_id, now=clock.now())

    @reg.handler(R.ShipmentDelivered)
    def on_delivered(ev: R.ShipmentDelivered, ctx: MessageContext, uow: UnitOfWork) -> None:
        if ev.direction is not R.ShipmentDirection.RETURN:
            return  # outbound deliveries are order-svc's concern
        if ev.return_id is None:
            log.warning("return delivery without returnId; ignored", order_id=ev.order_id)
            return
        fulfilments_for(uow).on_return_delivered(
            return_id=ev.return_id,
            shipment_id=ev.shipment_id,
            event_id=ctx.event_id,
            delivered_at=ev.delivered_at,
            now=clock.now(),
        )

    return reg
