"""inventory.commands.v1 handlers, registered by ce_type with the shared consumer runtime."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py.records import CommitReservation, ReleaseReservation, ReserveStock, RestockItems
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.ids import Clock

from inventory_svc.application.use_cases import Inventory
from inventory_svc.domain.model import StockLine

TOPICS = [ReserveStock.TOPIC]


def build_registry(inventory_for: Callable[[UnitOfWork], Inventory], clock: Clock) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(ReserveStock)
    def on_reserve(cmd: ReserveStock, ctx: MessageContext, uow: UnitOfWork) -> None:
        now = clock.now()
        inventory_for(uow).reserve(
            order_id=cmd.order_id,
            reservation_id=cmd.reservation_id,
            lines=[StockLine(x.sku, x.quantity) for x in cmd.lines],
            ttl_seconds=cmd.ttl_seconds,
            now=now,
            command_expired=ctx.is_expired(now),
        )

    @reg.handler(CommitReservation)
    def on_commit(cmd: CommitReservation, ctx: MessageContext, uow: UnitOfWork) -> None:
        inventory_for(uow).commit(order_id=cmd.order_id, reservation_id=cmd.reservation_id, now=clock.now())

    @reg.handler(ReleaseReservation)
    def on_release(cmd: ReleaseReservation, ctx: MessageContext, uow: UnitOfWork) -> None:
        inventory_for(uow).release(order_id=cmd.order_id, reservation_id=cmd.reservation_id, reason=cmd.reason, now=clock.now())

    @reg.handler(RestockItems)
    def on_restock(cmd: RestockItems, ctx: MessageContext, uow: UnitOfWork) -> None:
        inventory_for(uow).restock(
            order_id=cmd.order_id,
            return_id=cmd.return_id,
            restock_id=cmd.restock_id,
            lines=[StockLine(x.sku, x.quantity) for x in cmd.lines],
            now=clock.now(),
        )

    return reg
