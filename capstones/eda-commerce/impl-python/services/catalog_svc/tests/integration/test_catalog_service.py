"""catalog-svc with Postgres, migrations, the polling relay and the HTTP API (catalog.yaml)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from catalog_svc.adapters.inbound.http.routes import catalog_router
from catalog_svc.adapters.inbound.messaging.handlers import build_registry
from catalog_svc.config import Settings
from catalog_svc.main import catalog_factory
from contracts_py.records import StockLevelChanged
from edacommon.consumer import Outcome
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde
from edacommon.testing.openapi import validate_response
from edacommon.testing.service import ServiceHarness
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
SEED = Path(__file__).resolve().parents[5] / "infra" / "seed" / "products.json"


@pytest.fixture
def env(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[tuple[ServiceHarness, TestClient, Any]]:
    h = ServiceHarness(
        url=pg_url,
        migrations=MIGRATIONS,
        group="catalog-svc",
        serde=AvroSerde(schema_registry),
        clock=clock,
        metrics=metrics_reader[0],
    )
    s = Settings()
    infra = Infrastructure(settings=s, clock=clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
    catalog_for = catalog_factory(infra)
    app = create_app(
        s, readiness=Readiness(), instrument=False, routers=[catalog_router(h.db, catalog_for, clock, Authenticator(s))]
    )
    yield h, TestClient(app), build_registry(catalog_for)
    h.close()


def seed(c: TestClient) -> list[dict[str, Any]]:
    products = json.loads(SEED.read_text())
    for p in products:
        body = {k: v for k, v in p.items() if k not in ("sku", "onHand")}
        r = c.put(f"/admin/products/{p['sku']}", json=body)
        assert r.status_code == 200, r.text
        validate_response("catalog.yaml", "/admin/products/{sku}", "put", 200, r.json())
    return products


def test_seed_publishes_one_snapshot_per_sku_on_each_topic(env: Any) -> None:
    h, c, _ = env
    products = seed(c)
    out = h.published()
    prod = [p for p in out if p.topic == "catalog.product.v1"]
    price = [p for p in out if p.topic == "catalog.price.v1"]
    assert sorted(p.key for p in prod) == sorted(p["sku"] for p in products)
    assert sorted(p.key for p in price) == sorted(p["sku"] for p in products)
    p2 = next(p for p in price if p.key == "SKU-1002").value
    assert p2["listPrice"]["amountMinor"] == 7999 and p2["salePrice"]["amountMinor"] == 5999
    up = next(p for p in prod if p.key == "SKU-1007")
    assert up.value["status"] == "DISCONTINUED" and up.envelope["aggregateVersion"] == 1
    assert up.envelope["partitionKey"] == "SKU-1007" and up.envelope["aggregateType"] == "Product"
    seed(c)
    assert h.published() == [], "an unchanged write publishes nothing"


def test_price_change_publishes_price_snapshot_only(env: Any) -> None:
    h, c, _ = env
    seed(c)
    h.published()
    body = {
        "name": "Trail Running Shoe",
        "brand": "Northpeak",
        "categoryPath": ["Sport", "Footwear"],
        "attributes": {"colour": "blue", "size": "42"},
        "status": "ACTIVE",
        "weightGrams": 620,
        "listPrice": {"amountMinor": 11999, "currency": "EUR"},
    }
    assert c.put("/admin/products/SKU-1001", json=body).json()["version"] == 2
    (p,) = h.published()
    assert p.topic == "catalog.price.v1" and p.value["listPrice"]["amountMinor"] == 11999 and p.envelope["aggregateVersion"] == 2


def test_browse_and_stock_level_projection(env: Any) -> None:
    h, c, reg = env
    seed(c)
    assert c.get("/products/SKU-1001").json()["availability"] == "UNKNOWN"

    def level(available: int, version: int) -> Outcome:
        rec = h.command(
            StockLevelChanged,
            {"sku": "SKU-1001", "onHand": 50, "reserved": 50 - available, "available": available, "asOf": h.clock.now()},
            key="SKU-1001",
            producer="inventory-svc",
            aggregate_version=version,
        )
        return h.deliver(reg, rec)

    assert level(3, 5) is Outcome.SUCCESS
    assert c.get("/products/SKU-1001").json()["availability"] == "LOW_STOCK"
    assert level(40, 4) is Outcome.SUCCESS  # stale snapshot: dropped
    r = c.get("/products/SKU-1001")
    assert r.json()["availability"] == "LOW_STOCK"
    validate_response("catalog.yaml", "/products/{sku}", "get", 200, r.json())
    assert c.get("/products/SKU-1001", headers={"If-None-Match": r.headers["ETag"]}).status_code == 304
    lst = c.get("/products", params={"limit": 3}).json()
    validate_response("catalog.yaml", "/products", "get", 200, lst)
    assert len(lst["items"]) == 3 and lst["nextCursor"]
    rest = c.get("/products", params={"limit": 100, "cursor": lst["nextCursor"]}).json()["items"]
    skus = [p["sku"] for p in lst["items"] + rest]
    assert "SKU-1007" not in skus and len(skus) == 6, "discontinued products are not browsable"
    assert [p["sku"] for p in c.get("/products", params={"category": "Outdoor"}).json()["items"]] == [
        "SKU-1003",
        "SKU-1004",
        "SKU-1006",
    ]
    assert c.get("/products", params={"q": "lumo"}).json()["items"][0]["brand"] == "Lumo"
    assert c.get("/products/SKU-404").status_code == 404
    assert (
        c.put(
            "/admin/products/SKU-9", json={"name": "x", "status": "ACTIVE", "listPrice": {"amountMinor": 1.5, "currency": "EUR"}}
        ).status_code
        == 400
    )
