"""checkout-svc: catalog read model from compacted topics, carts, and POST /checkouts with
Idempotency-Key semantics (checklist §11 checkout-svc items), against real Postgres."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from checkout_svc.adapters.inbound.http.routes import checkout_router
from checkout_svc.adapters.inbound.messaging.handlers import build_registry
from checkout_svc.config import Settings
from checkout_svc.main import checkout_factory
from contracts_py import records as R
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.idempotency import IdempotencyStore
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde
from edacommon.testing.openapi import validate_response
from edacommon.testing.service import ServiceHarness
from fastapi.testclient import TestClient
from sqlalchemy import text

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
ADDRESS = {
    "recipientName": "Jane Doe",
    "line1": "Invalidenstrasse 1",
    "city": "Berlin",
    "postalCode": "10115",
    "countryCode": "DE",
}


class Env:
    def __init__(self, h: ServiceHarness) -> None:
        self.h = h
        s = Settings()
        infra = Infrastructure(settings=s, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.checkout_for = checkout_factory(infra)
        self.registry = build_registry(self.checkout_for)
        app = create_app(
            s,
            readiness=Readiness(),
            instrument=False,
            routers=[checkout_router(h.db, self.checkout_for, h.clock, Authenticator(s), IdempotencyStore(h.clock))],
        )
        self.c = TestClient(app, headers={"X-Debug-Subject": "cust-1"})

    def snapshot(
        self,
        sku: str,
        name: str,
        list_minor: int,
        *,
        status: str = "ACTIVE",
        available: int = 50,
        version: int = 1,
        sale: int | None = None,
    ) -> None:
        h = self.h
        h.deliver(
            self.registry,
            h.command(
                R.ProductUpserted,
                {"sku": sku, "name": name, "status": status},
                key=sku,
                producer="catalog-svc",
                aggregate_version=version,
            ),
        )
        h.deliver(
            self.registry,
            h.command(
                R.PriceChanged,
                {
                    "sku": sku,
                    "listPrice": {"amountMinor": list_minor, "currency": "EUR"},
                    "salePrice": {"amountMinor": sale, "currency": "EUR"} if sale else None,
                    "validFrom": h.clock.now(),
                },
                key=sku,
                producer="catalog-svc",
                aggregate_version=version,
            ),
        )
        h.deliver(
            self.registry,
            h.command(
                R.StockLevelChanged,
                {"sku": sku, "onHand": available, "reserved": 0, "available": available, "asOf": h.clock.now()},
                key=sku,
                producer="inventory-svc",
                aggregate_version=version,
            ),
        )

    def cart_with(self, *items: tuple[str, int]) -> str:
        r = self.c.post("/carts", json={"currency": "EUR"}, headers={"Idempotency-Key": f"cart-{len(items)}-{items}"})
        assert r.status_code == 201, r.text
        cart_id: str = r.json()["cartId"]
        for sku, q in items:
            assert self.c.put(f"/carts/{cart_id}/items/{sku}", json={"quantity": q}).status_code == 200
        return cart_id

    def checkout(self, cart_id: str, total: int, key: str = "k-1", token: str = "tok_visa_ok") -> Any:
        return self.c.post(
            "/checkouts",
            headers={"Idempotency-Key": key},
            json={
                "cartId": cart_id,
                "shippingAddress": ADDRESS,
                "contactEmail": "jane.doe@example.com",
                "shippingMethod": "STANDARD",
                "paymentMethodToken": token,
                "expectedTotal": {"amountMinor": total, "currency": "EUR"},
            },
        )


@pytest.fixture
def env(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Env]:
    h = ServiceHarness(
        url=pg_url,
        migrations=MIGRATIONS,
        group="checkout-svc",
        serde=AvroSerde(schema_registry),
        clock=clock,
        metrics=metrics_reader[0],
    )
    e = Env(h)
    e.snapshot("SKU-1001", "Trail Running Shoe", 12999)
    e.snapshot("SKU-1007", "Old Model Jacket", 19900, status="DISCONTINUED")
    e.snapshot("SKU-1005", "Limited Edition Watch", 89900, available=1)
    yield e
    h.close()


def test_catalog_view_rebuild_from_offset_zero_is_identical(env: Env) -> None:
    def rows() -> list[Any]:
        with env.h.db.unit_of_work() as uow:
            return list(
                uow.session.execute(
                    text(
                        "SELECT sku, name, status, list_minor, sale_minor, currency, available, "
                        "product_version, price_version, stock_version FROM catalog_view ORDER BY sku"
                    )
                ).all()
            )

    before = rows()
    env.snapshot("SKU-1001", "Trail Running Shoe", 99, version=0)  # an older snapshot never wins
    assert rows() == before
    with env.h.db.unit_of_work() as uow:
        uow.session.execute(text("DELETE FROM catalog_view"))
        uow.session.execute(text("DELETE FROM inbox"))  # a new group id re-reads from offset 0
    env.snapshot("SKU-1001", "Trail Running Shoe", 12999)
    env.snapshot("SKU-1007", "Old Model Jacket", 19900, status="DISCONTINUED")
    env.snapshot("SKU-1005", "Limited Edition Watch", 89900, available=1)
    assert rows() == before


def test_cart_api_etags_and_refusals(env: Env) -> None:
    c = env.c
    r = c.post("/carts", json={}, headers={"Idempotency-Key": "c1"})
    assert r.status_code == 201 and r.headers["Location"].startswith("/carts/")
    validate_response("checkout.yaml", "/carts", "post", 201, r.json())
    cart = r.json()["cartId"]
    assert c.post("/carts", json={}, headers={"Idempotency-Key": "c1"}).json()["cartId"] == cart
    r = c.put(f"/carts/{cart}/items/SKU-1001", json={"quantity": 2}, headers={"If-Match": '"1"'})
    assert r.status_code == 200 and r.headers["ETag"] == '"2"'
    body = r.json()
    validate_response("checkout.yaml", "/carts/{cartId}/items/{sku}", "put", 200, body)
    assert body["subtotal"] == {"amountMinor": 25998, "currency": "EUR"} and body["lines"][0]["availability"] == "IN_STOCK"
    assert c.put(f"/carts/{cart}/items/SKU-1001", json={"quantity": 3}, headers={"If-Match": '"1"'}).status_code == 412
    r = c.put(f"/carts/{cart}/items/SKU-1007", json={"quantity": 1})
    assert r.status_code == 422 and r.json()["type"].endswith("/product-discontinued")
    assert c.put(f"/carts/{cart}/items/SKU-404", json={"quantity": 1}).status_code == 422
    assert c.put(f"/carts/{cart}/items/SKU-1005", json={"quantity": 2}).json()["type"].endswith("/insufficient-stock")
    assert c.put(f"/carts/{cart}/items/SKU-1001", json={"quantity": 0}).status_code == 400
    g = c.get(f"/carts/{cart}")
    validate_response("checkout.yaml", "/carts/{cartId}", "get", 200, g.json())
    assert c.get(f"/carts/{cart}", headers={"X-Debug-Subject": "someone-else"}).status_code == 404
    assert c.delete(f"/carts/{cart}/items/SKU-1001").json()["lines"] == []


def test_checkout_emits_checkout_submitted_and_replays_idempotently(env: Env) -> None:
    cart = env.cart_with(("SKU-1001", 2))
    env.h.published()
    r = env.checkout(cart, 25998)
    assert r.status_code == 202, r.text
    validate_response("checkout.yaml", "/checkouts", "post", 202, r.json())
    order_id = r.json()["orderId"]
    assert r.headers["Location"] == f"/orders/{order_id}" and "Idempotent-Replayed" not in r.headers
    (evt,) = env.h.published()
    assert evt.topic == "checkout.events.v1" and evt.key == order_id and evt.type.endswith("CheckoutSubmitted")
    v = evt.value
    assert v["total"] == {"amountMinor": 25998, "currency": "EUR"} and v["shippingFee"]["amountMinor"] == 0
    assert v["contactEmail"] == "jane.doe@example.com" and v["customerId"] == "cust-1"
    env_ = evt.envelope
    assert env_["correlationId"] == order_id and env_["partitionKey"] == order_id and env_["causationId"] is None
    assert env_["producer"] == "checkout-svc" and env_["aggregateType"] == "Checkout"
    again = env.checkout(cart, 25998)
    assert again.status_code == 202 and again.json()["orderId"] == order_id
    assert again.headers["Idempotent-Replayed"] == "true"
    assert env.h.published() == [], "a replay never creates a second order"
    other = env.checkout(cart, 25999)
    assert other.status_code == 422 and other.json()["type"].endswith("/idempotency-key-reused")


def test_price_mismatch_and_empty_cart_are_422(env: Env) -> None:
    cart = env.cart_with(("SKU-1001", 1))
    r = env.checkout(cart, 100, key="k-x")
    assert r.status_code == 422 and r.json()["type"].endswith("/price-changed")
    assert env.checkout(cart, 12999, key="k-x").status_code == 202, "a refused request does not burn the key"
    empty = env.cart_with()
    assert env.checkout(empty, 0, key="k-e").json()["type"].endswith("/cart-empty")


def test_concurrent_same_key_is_409(env: Env) -> None:
    from edacommon.idempotency import _lock_key
    from sqlalchemy import create_engine

    cart = env.cart_with(("SKU-1001", 1))
    eng = create_engine(env.h.url)
    held, release = threading.Event(), threading.Event()

    def hold() -> None:  # another request with the same key is mid-transaction
        with eng.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _lock_key("cust-1", "k-c")})
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    r = env.checkout(cart, 12999, key="k-c")
    release.set()
    t.join()
    eng.dispose()
    assert r.status_code == 409 and r.headers["Retry-After"]
    assert env.checkout(cart, 12999, key="k-c").status_code == 202


def test_order_events_update_checkout_row(env: Env) -> None:
    cart = env.cart_with(("SKU-1001", 1))
    order_id = env.checkout(cart, 12999).json()["orderId"]
    env.h.deliver(
        env.registry,
        env.h.command(
            R.OrderCancelled, {"orderId": order_id, "reason": "OUT_OF_STOCK", "cancelledAt": env.h.clock.now()}, key=order_id
        ),
    )
    with env.h.db.unit_of_work() as uow:
        assert uow.session.execute(text("SELECT order_status FROM checkout")).scalar_one() == "CANCELLED"
