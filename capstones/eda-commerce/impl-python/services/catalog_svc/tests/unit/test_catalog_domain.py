from __future__ import annotations

import pytest
from catalog_svc.domain.product import Price, Product, ProductStatus, availability, decide_upsert, newer

P = Product("SKU-1", "Shoe", ProductStatus.ACTIVE, Price(12999, "EUR"))


def test_first_upsert_publishes_both_snapshots() -> None:
    d = decide_upsert(None, P)
    assert d.product.version == 1 and d.product_changed and d.price_changed


def test_unchanged_upsert_publishes_nothing() -> None:
    d = decide_upsert(decide_upsert(None, P).product, P)
    assert not d.product_changed and not d.price_changed and d.product.version == 1


def test_price_only_change() -> None:
    from dataclasses import replace

    first = decide_upsert(None, P).product
    d = decide_upsert(first, replace(P, price=Price(12999, "EUR", 9999)))
    assert d.price_changed and not d.product_changed and d.product.version == 2


def test_price_rules() -> None:
    with pytest.raises(ValueError, match="exceed"):
        Price(100, "EUR", 200)


def test_availability_and_version_guard() -> None:
    assert [availability(x) for x in (None, 0, 3, 50)] == ["UNKNOWN", "OUT_OF_STOCK", "LOW_STOCK", "IN_STOCK"]
    assert newer(None, 1) and newer(1, 2) and not newer(2, 2) and not newer(3, 2)
