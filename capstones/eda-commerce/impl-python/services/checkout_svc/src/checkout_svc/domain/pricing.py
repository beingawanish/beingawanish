"""Cart pricing and checkout rules (architecture §9 countermeasures: reread value). Pure.

Prices are VAT-inclusive (EU retail). Tax is the VAT contained in each line, rounded half-even at
line level (guide §6.2); shipping is a flat fee per method, free for STANDARD above a threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from checkout_svc.domain.money import Money

VAT_RATE = Decimal("0.19")
FREE_SHIPPING_FROM_MINOR = 5000
SHIPPING_FEE_MINOR = {"STANDARD": 499, "EXPRESS": 999}
MAX_QUANTITY = 99


class CheckoutRefused(Exception):
    def __init__(self, problem_type: str, detail: str) -> None:
        super().__init__(detail)
        self.problem_type = problem_type
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """checkout's local read model of one SKU (catalog + price + stock snapshots, ADR-0010)."""

    sku: str
    name: str | None
    status: str | None  # ACTIVE | DISCONTINUED | UNKNOWN | None (no product snapshot yet)
    list_minor: int | None
    sale_minor: int | None
    currency: str | None
    available: int | None
    priced_as_of: datetime | None

    def unit_price(self) -> Money:
        if self.list_minor is None or self.currency is None:
            raise CheckoutRefused("price-unavailable", f"{self.sku} has no price yet")
        return Money(self.sale_minor if self.sale_minor is not None else self.list_minor, self.currency)

    def availability(self) -> str:
        if self.available is None:
            return "UNKNOWN"
        if self.available <= 0:
            return "OUT_OF_STOCK"
        return "LOW_STOCK" if self.available <= 5 else "IN_STOCK"


def check_can_add(entry: CatalogEntry | None, sku: str, quantity: int) -> None:
    if not 1 <= quantity <= MAX_QUANTITY:
        raise CheckoutRefused("validation-error", "quantity must be between 1 and 99")
    if entry is None or entry.status is None or entry.name is None:
        raise CheckoutRefused("unknown-sku", f"{sku} is not in the catalog")
    if entry.status != "ACTIVE":
        raise CheckoutRefused("product-discontinued", f"{sku} is discontinued")
    # Advisory only: the reservation is the real check (ADR-0016).
    if entry.available is not None and quantity > entry.available:
        raise CheckoutRefused("insufficient-stock", f"only {max(entry.available, 0)} of {sku} available")
    entry.unit_price()


@dataclass(frozen=True, slots=True)
class PricedLine:
    sku: str
    product_name: str
    quantity: int
    unit_price: Money
    line_total: Money
    tax: Money
    availability: str


@dataclass(frozen=True, slots=True)
class Quote:
    lines: tuple[PricedLine, ...]
    subtotal: Money
    shipping_fee: Money
    tax: Money
    total: Money
    priced_at: datetime


def price_lines(
    items: list[tuple[str, int]], catalog: dict[str, CatalogEntry], currency: str, now: datetime
) -> tuple[tuple[PricedLine, ...], Money, datetime]:
    lines = []
    subtotal = Money.zero(currency)
    freshness = [now]
    for sku, qty in items:
        e = catalog.get(sku)
        if e is None:
            raise CheckoutRefused("unknown-sku", f"{sku} is not in the catalog")
        unit = e.unit_price()
        total = unit.times(qty)
        line = PricedLine(sku, e.name or sku, qty, unit, total, total.share(VAT_RATE / (1 + VAT_RATE)), e.availability())
        lines.append(line)
        subtotal = subtotal + total
        if e.priced_as_of:
            freshness.append(e.priced_as_of)
    return tuple(lines), subtotal, min(freshness)


def quote(
    items: list[tuple[str, int]], catalog: dict[str, CatalogEntry], currency: str, shipping_method: str, now: datetime
) -> Quote:
    lines, subtotal, priced_at = price_lines(items, catalog, currency, now)
    fee = SHIPPING_FEE_MINOR.get(shipping_method)
    if fee is None:
        raise CheckoutRefused("validation-error", f"unknown shipping method {shipping_method}")
    if shipping_method == "STANDARD" and subtotal.amount_minor >= FREE_SHIPPING_FROM_MINOR:
        fee = 0
    shipping = Money(fee, currency)
    tax = Money.zero(currency)
    for line in lines:
        tax = tax + line.tax
    tax = tax + shipping.share(VAT_RATE / (1 + VAT_RATE))
    return Quote(lines, subtotal, shipping, tax, subtotal + shipping, priced_at)


def validate_checkout(
    cart_status: str, items: list[tuple[str, int]], catalog: dict[str, CatalogEntry], q: Quote, expected: Money
) -> None:
    if cart_status != "OPEN":
        raise CheckoutRefused("cart-not-open", "the cart was already checked out")
    if not items:
        raise CheckoutRefused("cart-empty", "the cart is empty")
    for sku, _ in items:
        e = catalog.get(sku)
        if e is None or e.status != "ACTIVE":
            raise CheckoutRefused("product-discontinued", f"{sku} can no longer be ordered")
    if expected != q.total:
        raise CheckoutRefused("price-changed", f"total is now {q.total}, the client expected {expected}")


class CartStatus(StrEnum):
    OPEN = "OPEN"
    CHECKED_OUT = "CHECKED_OUT"
    ABANDONED = "ABANDONED"
