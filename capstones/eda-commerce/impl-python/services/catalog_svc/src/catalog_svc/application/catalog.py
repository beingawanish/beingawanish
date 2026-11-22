"""catalog-svc use cases: upsert a product (publishing snapshots), project stock levels, browse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from contracts_py.records import PriceChanged, ProductUpserted
from edacommon.envelope import OutgoingMessage

from catalog_svc.domain.product import Product, StockSnapshot, decide_upsert, newer


class CatalogRepository(Protocol):
    def get(self, sku: str, *, for_update: bool = False) -> Product | None: ...

    def save(self, p: Product, now: datetime) -> None: ...

    def stock_version(self, sku: str) -> int | None: ...

    def save_stock(self, s: StockSnapshot) -> None: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...


def _money(minor: int, cur: str) -> dict[str, Any]:
    return {"amountMinor": minor, "currency": cur}


def product_upserted(p: Product) -> OutgoingMessage:
    return OutgoingMessage(
        topic=ProductUpserted.TOPIC,
        record_type=ProductUpserted.AVRO_NAME,
        key=p.sku,
        aggregate_type="Product",
        aggregate_id=p.sku,
        aggregate_version=p.version,
        body={
            "sku": p.sku,
            "name": p.name,
            "description": p.description,
            "brand": p.brand,
            "categoryPath": list(p.category_path),
            "attributes": dict(p.attributes),
            "status": p.status.value,
            "weightGrams": p.weight_grams,
            "imageUrls": list(p.image_urls),
        },
    )


def price_changed(p: Product, now: datetime) -> OutgoingMessage:
    pr = p.price
    return OutgoingMessage(
        topic=PriceChanged.TOPIC,
        record_type=PriceChanged.AVRO_NAME,
        key=p.sku,
        aggregate_type="Price",
        aggregate_id=p.sku,
        aggregate_version=p.version,
        body={
            "sku": p.sku,
            "priceListId": pr.price_list_id,
            "listPrice": _money(pr.list_minor, pr.currency),
            "salePrice": _money(pr.sale_minor, pr.currency) if pr.sale_minor is not None else None,
            "validFrom": now,
            "validUntil": None,
        },
    )


@dataclass
class Catalog:
    repo: CatalogRepository
    events: EventPublisher

    def upsert(self, incoming: Product, now: datetime) -> Product:
        d = decide_upsert(self.repo.get(incoming.sku, for_update=True), incoming)
        if d.product_changed or d.price_changed:
            self.repo.save(d.product, now)
        if d.product_changed:
            self.events.publish(product_upserted(d.product))
        if d.price_changed:
            self.events.publish(price_changed(d.product, now))
        return d.product

    def on_stock_level(self, s: StockSnapshot) -> bool:
        if not newer(self.repo.stock_version(s.sku), s.version):
            return False
        self.repo.save_stock(s)
        return True
