from __future__ import annotations

from datetime import UTC, datetime

import pytest
from checkout_svc.domain.money import CurrencyMismatch, Money
from checkout_svc.domain.pricing import CatalogEntry, CheckoutRefused, check_can_add, quote, validate_checkout

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)


def entry(
    sku: str, list_minor: int = 12999, sale: int | None = None, status: str = "ACTIVE", available: int | None = 50
) -> CatalogEntry:
    return CatalogEntry(sku, f"name {sku}", status, list_minor, sale, "EUR", available, NOW)


def test_money_rules() -> None:
    assert Money(100, "EUR") + Money(1, "EUR") == Money(101, "EUR")
    with pytest.raises(CurrencyMismatch):
        Money(1, "EUR") + Money(1, "USD")
    with pytest.raises(TypeError):
        Money(1.5, "EUR")  # type: ignore[arg-type]
    # banker's rounding: 0.5 rounds to even
    assert Money(5, "EUR").share(__import__("decimal").Decimal("0.5")) == Money(2, "EUR")
    assert Money(15, "EUR").share(__import__("decimal").Decimal("0.5")) == Money(8, "EUR")


def test_quote_sale_price_shipping_and_included_vat() -> None:
    cat = {"A": entry("A", 7999, 5999), "B": entry("B", 1999)}
    q = quote([("A", 1), ("B", 2)], cat, "EUR", "STANDARD", NOW)
    assert q.subtotal == Money(5999 + 3998, "EUR") and q.shipping_fee == Money(0, "EUR")  # free above 50 EUR
    assert q.total == q.subtotal
    assert q.tax == Money(958 + 638, "EUR")  # 5999*19/119 -> 957.8 -> 958 ; 3998*19/119 -> 638.3 -> 638
    small = quote([("B", 1)], cat, "EUR", "EXPRESS", NOW)
    assert small.shipping_fee == Money(999, "EUR") and small.total == Money(2998, "EUR")


def test_add_rules() -> None:
    check_can_add(entry("A"), "A", 2)
    for e, qty, ptype in [
        (None, 1, "unknown-sku"),
        (entry("A", status="DISCONTINUED"), 1, "product-discontinued"),
        (entry("A", available=1), 2, "insufficient-stock"),
        (entry("A"), 100, "validation-error"),
    ]:
        with pytest.raises(CheckoutRefused) as ei:
            check_can_add(e, "A", qty)
        assert ei.value.problem_type == ptype


def test_expected_total_mismatch_is_refused() -> None:
    cat = {"A": entry("A")}
    q = quote([("A", 1)], cat, "EUR", "STANDARD", NOW)
    validate_checkout("OPEN", [("A", 1)], cat, q, q.total)
    with pytest.raises(CheckoutRefused) as ei:
        validate_checkout("OPEN", [("A", 1)], cat, q, Money(1, "EUR"))
    assert ei.value.problem_type == "price-changed"
