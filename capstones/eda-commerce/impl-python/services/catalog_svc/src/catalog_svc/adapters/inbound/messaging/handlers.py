"""catalog-svc consumes inventory.stock-level.v1 into stock_level_view (browse availability)."""

from __future__ import annotations

from collections.abc import Callable

from contracts_py.records import StockLevelChanged
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext

from catalog_svc.application.catalog import Catalog
from catalog_svc.domain.product import StockSnapshot

TOPICS = [StockLevelChanged.TOPIC]


def build_registry(catalog_for: Callable[[UnitOfWork], Catalog]) -> HandlerRegistry:
    reg = HandlerRegistry()

    @reg.handler(StockLevelChanged)
    def on_level(m: StockLevelChanged, ctx: MessageContext, uow: UnitOfWork) -> None:
        catalog_for(uow).on_stock_level(StockSnapshot(m.sku, m.available, m.envelope.aggregate_version, m.as_of))

    return reg
