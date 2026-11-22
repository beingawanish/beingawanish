"""Ports of checkout-svc."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from edacommon.envelope import OutgoingMessage

from checkout_svc.domain.pricing import CatalogEntry


@dataclass(frozen=True, slots=True)
class Cart:
    cart_id: str
    customer_id: str
    status: str
    currency: str
    version: int
    items: tuple[tuple[str, int], ...]


class CartRepository(Protocol):
    def create(self, cart: Cart, now: datetime) -> None: ...

    def get(self, cart_id: str, *, for_update: bool = False) -> Cart | None: ...

    def save(self, cart: Cart, now: datetime) -> None: ...

    def record_checkout(self, *, checkout_id: str, order_id: str, cart: Cart, total_minor: int, now: datetime) -> None: ...

    def set_order_status(self, order_id: str, status: str) -> None: ...


class CatalogView(Protocol):
    def entries(self, skus: list[str]) -> dict[str, CatalogEntry]: ...

    def apply_product(self, sku: str, name: str, status: str, version: int, at: datetime) -> bool: ...

    def apply_price(
        self, sku: str, list_minor: int, sale_minor: int | None, currency: str, version: int, at: datetime
    ) -> bool: ...

    def apply_stock(self, sku: str, available: int, version: int, at: datetime) -> bool: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...


Json = dict[str, Any]
