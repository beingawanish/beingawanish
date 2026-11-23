"""shipping-svc consumers: OrderPacked on fulfilment.events.v1 (choreography) and IssueReturnLabel on
shipping.commands.v1. Every other fulfilment event is unregistered and counted as ``ignored``."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from shipping_svc.application.use_cases import Shipments

TOPICS = [R.OrderPacked.TOPIC, R.IssueReturnLabel.TOPIC]


def build_registry(shipments_for: Callable[[UnitOfWork], Shipments], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(R.OrderPacked)
    def on_packed(ev: R.OrderPacked, ctx: MessageContext, uow: UnitOfWork) -> None:
        shipments_for(uow).on_order_packed(
            order_id=ev.order_id,
            fulfilment_id=ev.fulfilment_id,
            warehouse_id=ev.warehouse_id,
            ship_to=ev.ship_to.to_avro(),
            parcel_count=len(ev.parcels),
            shipping_method=ev.shipping_method.value,
            trigger_id=ctx.event_id,
            correlation_id=ctx.correlation_id,
            now=clock.now(),
        )

    @reg.handler(R.IssueReturnLabel)
    def on_issue(cmd: R.IssueReturnLabel, ctx: MessageContext, uow: UnitOfWork) -> None:
        shipments_for(uow).issue_return_label(
            order_id=cmd.order_id,
            return_id=cmd.return_id,
            shipment_id=cmd.shipment_id,
            pickup_from=cmd.pickup_from.to_avro(),
            to_warehouse_id=cmd.to_warehouse_id,
            trigger_id=ctx.event_id,
            correlation_id=ctx.correlation_id,
            now=clock.now(),
        )

    return reg
