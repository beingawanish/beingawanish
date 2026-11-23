"""Catalog domain: products, prices and the availability shown on product pages. Pure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

LOW_STOCK_THRESHOLD = 5


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


@dataclass(frozen=True, slots=True)
class Price:
    list_minor: int
    currency: str
    sale_minor: int | None = None
    price_list_id: str = "retail-eu"

    def __post_init__(self) -> None:
        if self.list_minor < 0 or (self.sale_minor is not None and self.sale_minor < 0):
            raise ValueError("prices must be >= 0")
        if self.sale_minor is not None and self.sale_minor > self.list_minor:
            raise ValueError("salePrice must not exceed listPrice")


@dataclass(frozen=True, slots=True)
class Product:
    sku: str
    name: str
    status: ProductStatus
    price: Price
    description: str | None = None
    brand: str | None = None
    category_path: tuple[str, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)
    weight_grams: int | None = None
    image_urls: tuple[str, ...] = ()
    version: int = 0

    def content_equals(self, other: Product) -> bool:
        a = (
            self.name,
            self.status,
            self.description,
            self.brand,
            self.category_path,
            self.attributes,
            self.weight_grams,
            self.image_urls,
        )
        b = (
            other.name,
            other.status,
            other.description,
            other.brand,
            other.category_path,
            other.attributes,
            other.weight_grams,
            other.image_urls,
        )
        return a == b


@dataclass(frozen=True, slots=True)
class UpsertDecision:
    product: Product
    product_changed: bool
    price_changed: bool


def decide_upsert(existing: Product | None, incoming: Product) -> UpsertDecision:
    """Every change publishes a full snapshot (compacted topic). Unchanged writes publish nothing."""
    if existing is None:
        return UpsertDecision(_v(incoming, 1), True, True)
    product_changed = not existing.content_equals(incoming)
    price_changed = existing.price != incoming.price
    version = existing.version + (1 if (product_changed or price_changed) else 0)
    return UpsertDecision(_v(incoming, version), product_changed, price_changed)


def _v(p: Product, version: int) -> Product:
    from dataclasses import replace

    return replace(p, version=version)


def availability(available: int | None) -> str:
    if available is None:
        return "UNKNOWN"
    if available <= 0:
        return "OUT_OF_STOCK"
    if available <= LOW_STOCK_THRESHOLD:
        return "LOW_STOCK"
    return "IN_STOCK"


@dataclass(frozen=True, slots=True)
class StockSnapshot:
    sku: str
    available: int
    version: int
    as_of: datetime


def newer(current_version: int | None, incoming_version: int) -> bool:
    """Compacted-topic snapshots replace the row only when strictly newer (ADR-0010)."""
    return current_version is None or incoming_version > current_version
