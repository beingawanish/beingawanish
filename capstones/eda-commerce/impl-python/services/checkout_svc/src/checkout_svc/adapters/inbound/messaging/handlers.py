"""checkout-svc consumers: the catalog read model from three compacted topics (read from offset 0,
ADR-0010) and order outcomes for the checkout row."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py import records as R
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext

from checkout_svc.application.checkout import Checkout

TOPICS = [R.ProductUpserted.TOPIC, R.PriceChanged.TOPIC, R.StockLevelChanged.TOPIC, R.OrderPlaced.TOPIC]


def build_registry(checkout_for: Callable[[UnitOfWork], Checkout]) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(R.ProductUpserted)
    def on_product(m: R.ProductUpserted, ctx: MessageContext, uow: UnitOfWork) -> None:
        checkout_for(uow).catalog.apply_product(
            m.sku, m.name, m.status.value, m.envelope.aggregate_version, m.envelope.occurred_at
        )

    @reg.handler(R.PriceChanged)
    def on_price(m: R.PriceChanged, ctx: MessageContext, uow: UnitOfWork) -> None:
        checkout_for(uow).catalog.apply_price(
            m.sku,
            m.list_price.amount_minor,
            m.sale_price.amount_minor if m.sale_price else None,
            m.list_price.currency,
            m.envelope.aggregate_version,
            m.envelope.occurred_at,
        )

    @reg.handler(R.StockLevelChanged)
    def on_stock(m: R.StockLevelChanged, ctx: MessageContext, uow: UnitOfWork) -> None:
        checkout_for(uow).catalog.apply_stock(m.sku, m.available, m.envelope.aggregate_version, m.as_of)

    def status(name: str) -> Callable[[object, MessageContext, UnitOfWork], None]:
        def handle(m: object, ctx: MessageContext, uow: UnitOfWork) -> None:
            checkout_for(uow).carts.set_order_status(getattr(m, "order_id"), name)  # noqa: B009

        return handle

    reg.register(R.OrderPlaced, status("PLACED"))
    reg.register(R.OrderConfirmed, status("CONFIRMED"))
    reg.register(R.OrderCancelled, status("CANCELLED"))
    return reg
