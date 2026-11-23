"""order-svc with real Postgres, its migrations, the consumer runtime, the polling relay and an S3
API (moto): the saga end to end, invoice claim check, deadlines, ops and the Orders API."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any

import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheck
from edacommon.consumer import Outcome
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.idempotency import IdempotencyStore
from edacommon.saga.ops import saga_ops_router
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from edacommon.testing.openapi import validate_response
from fastapi.testclient import TestClient
from order_svc.adapters.inbound.http.routes import ops_caller, orders_router
from order_svc.adapters.inbound.jobs.deadlines import order_deadline_sweeper
from order_svc.adapters.projector.projection import build_registry as projector_registry
from sqlalchemy import create_engine, text

from .conftest import ORDER, Svc, checkout_body, drive_to_delivered

pytestmark = pytest.mark.integration


def app(svc: Svc) -> TestClient:
    auth = Authenticator(svc.settings)

    def retry_step(uow: Any, row: Any) -> bool:
        return svc.saga_for(uow).retry_step(uow, row)

    a = create_app(
        svc.settings,
        readiness=Readiness(),
        instrument=False,
        routers=[
            orders_router(svc.h.db, svc.documents, auth),
            saga_ops_router(
                db=svc.h.db, idempotency=IdempotencyStore(svc.h.clock), retry_step=retry_step, caller_of=ops_caller(auth)
            ),
        ],
    )
    return TestClient(a, follow_redirects=False)


def test_shared_tables_match_contract(svc: Svc) -> None:
    tables = ["outbox", "inbox", "idempotency_key", "saga_instance", "saga_transition"]
    with fresh_database("contract") as ref:
        e = create_engine(ref)
        with e.begin() as c:
            c.exec_driver_sql(contract_sql_path().read_text())
        e.dispose()
        assert information_schema_columns(svc.h.url, tables) == information_schema_columns(ref, tables)


def test_checkout_starts_saga_with_order_placed_and_reserve_stock(svc: Svc) -> None:
    rec = svc.h.command(R.CheckoutSubmitted, checkout_body(), key=ORDER, producer="checkout-svc")
    assert svc.h.deliver(svc.registry, rec) is Outcome.SUCCESS
    out = svc.out()
    assert [p.type.rsplit(".", 1)[1] for p in out] == ["ReserveStock", "OrderPlaced"]
    reserve, placed = out
    assert reserve.topic == "inventory.commands.v1" and placed.topic == "order.events.v1"
    for p in out:
        env = p.envelope
        assert env["causationId"] == rec.event_id and env["correlationId"] == ORDER and env["partitionKey"] == ORDER
        assert env["producer"] == "order-svc" and p.key == ORDER
    assert placed.envelope["aggregateType"] == "Order" and placed.envelope["aggregateVersion"] == 1
    assert placed.value["contactEmail"] == "jane.doe@example.com" and placed.value["total"]["amountMinor"] == 25998
    assert reserve.value["lines"] == [{"sku": "SKU-1001", "quantity": 2}] and reserve.value["ttlSeconds"] == 900
    # duplicate delivery and a resent CheckoutSubmitted (new eventId) both produce nothing new
    assert svc.h.deliver(svc.registry, rec) is Outcome.DUPLICATE
    svc.send(R.CheckoutSubmitted, checkout_body(), producer="checkout-svc")
    assert svc.out() == []


def test_happy_path_to_delivered_with_invoice_claim_check(svc: Svc, metrics_reader: Any) -> None:
    drive_to_delivered(svc)
    order_events = [p for p in svc.all if p.topic == "order.events.v1"]
    names = [p.type.rsplit(".", 1)[1] for p in order_events]
    assert names == ["OrderPlaced", "OrderConfirmed", "OrderShipped", "InvoiceIssued", "OrderDelivered"]
    versions = [p.envelope["aggregateVersion"] for p in order_events]
    assert versions == sorted(versions) and len(set(versions)) == len(versions), "strictly increasing per order"
    inv = next(p for p in order_events if p.type.endswith("InvoiceIssued")).value
    assert inv["invoiceNumber"] == f"INV-{svc.h.clock.now().year}-000001"
    doc = inv["document"]
    assert doc["bucket"] == "invoices"
    assert doc["objectKey"] == f"order/{svc.h.clock.now():%Y/%m}/{ORDER}/{inv['invoiceId']}.pdf", "deterministic key"
    pdf = svc.cc.get(ClaimCheck.from_avro(doc))  # consumer-side verification: size + sha256
    assert pdf.startswith(b"%PDF") and hashlib.sha256(pdf).hexdigest() == doc["sha256"]
    delivered = order_events[-1].value
    assert delivered["returnWindowEndsAt"] - delivered["deliveredAt"] == timedelta(days=30)
    cmds = [p.type.rsplit(".", 1)[1] for p in svc.all if ".commands." in p.topic]
    assert cmds == ["ReserveStock", "AuthorizePayment", "CommitReservation", "RequestFulfilment", "CapturePayment"]
    reader = metrics_reader[1]
    assert counter_value(reader, "eda.saga.outcomes", saga_type="ORDER", outcome="DELIVERED") == 1
    with svc.h.db.unit_of_work() as uow:
        assert uow.session.execute(text("SELECT status FROM orders")).scalar_one() == "DELIVERED"
        assert uow.session.execute(text("SELECT state, deadline_at FROM saga_instance")).one() == ("DELIVERED", None)


def test_invoice_numbers_are_gapless_across_orders_and_rollbacks(svc: Svc) -> None:
    from order_svc.adapters.outbound.persistence.repositories import SqlInvoiceRepository

    with pytest.raises(RuntimeError), svc.h.db.unit_of_work() as uow:
        SqlInvoiceRepository(uow.session).next_number(2026)
        raise RuntimeError("rendering failed")
    drive_to_delivered(svc, "0193a1c4-0000-7000-8000-00000000c010")
    drive_to_delivered(svc, "0193a1c4-0000-7000-8000-00000000c011")
    nums = sorted(p.value["invoiceNumber"] for p in svc.all if p.type.endswith("InvoiceIssued"))
    y = svc.h.clock.now().year
    assert nums == [f"INV-{y}-000001", f"INV-{y}-000002"]


def test_deadline_sweeper_resends_with_same_business_id(svc: Svc, metrics_reader: Any) -> None:
    svc.send(R.CheckoutSubmitted, checkout_body(), producer="checkout-svc")
    first = svc.out()[0].value
    sweeper = order_deadline_sweeper(svc.h.db, svc.saga_for, svc.h.clock, svc.h.metrics)
    assert sweeper.run_once() == 0
    svc.h.clock.advance(timedelta(seconds=31))
    assert sweeper.run_once() == 1
    (resend,) = svc.out()
    assert resend.type.endswith("ReserveStock") and resend.value["reservationId"] == first["reservationId"]
    assert resend.envelope["causationId"] is None, "timer-caused"
    assert counter_value(metrics_reader[1], "eda.saga.step.timeouts", state="RESERVING_STOCK") == 1


def test_decline_path_releases_and_cancels(svc: Svc) -> None:
    svc.send(R.CheckoutSubmitted, checkout_body(token="tok_decline"), producer="checkout-svc")
    svc.out()
    rid = svc.last_command("ReserveStock")["reservationId"]
    now = svc.h.clock.now()
    svc.send(R.StockReserved, {"orderId": ORDER, "reservationId": rid, "lines": [], "expiresAt": now})
    svc.out()
    pid = svc.last_command("AuthorizePayment")["paymentId"]
    svc.send(R.PaymentDeclined, {"orderId": ORDER, "paymentId": pid, "reason": "CARD_DECLINED", "declinedAt": now})
    (rel,) = svc.out()
    assert rel.type.endswith("ReleaseReservation") and rel.value["reservationId"] == rid
    svc.send(R.ReservationReleased, {"orderId": ORDER, "reservationId": rid, "reason": "PAYMENT_DECLINED", "releasedAt": now})
    (cancelled,) = svc.out()
    assert cancelled.type.endswith("OrderCancelled")
    assert cancelled.value["reason"] == "PAYMENT_DECLINED" and cancelled.value["paymentVoided"] is False


def test_reply_before_saga_exists_is_retried_later(svc: Svc) -> None:
    assert (
        svc.send(
            R.ReservationReleased,
            {"orderId": "nope", "reservationId": "r", "reason": "x", "releasedAt": svc.h.clock.now()},
            key="nope",
        )
        is Outcome.RETRY
    )
    assert svc.h.producer.records[-1].topic == "order-svc.retry.10s"


def test_unknown_enum_value_handled(svc: Svc) -> None:
    drive_to_delivered(svc)
    # A ShipmentException whose code a newer producer added decodes as UNKNOWN: recorded, no exception.
    assert (
        svc.send(
            R.ShipmentException,
            {"orderId": ORDER, "shipmentId": "ship-1", "direction": "UNKNOWN", "code": "UNKNOWN", "raisedAt": svc.h.clock.now()},
        )
        is Outcome.SUCCESS
    )


def test_orders_api_fallback_then_read_model_etag_and_invoice(svc: Svc) -> None:
    c = app(svc)
    headers = {"X-Debug-Subject": "cust-1"}
    svc.send(R.CheckoutSubmitted, checkout_body(), producer="checkout-svc")
    r = c.get(f"/orders/{ORDER}", headers=headers)
    assert r.status_code == 200 and r.json()["source"] == "WRITE_MODEL_FALLBACK" and r.json()["status"] == "PENDING"
    assert r.headers["Retry-After"] == "1"
    validate_response("orders.yaml", "/orders/{orderId}", "get", 200, r.json())
    assert c.get(f"/orders/{ORDER}", headers={"X-Debug-Subject": "someone-else"}).status_code == 404
    assert c.get("/orders/0193a1c4-0000-7000-8000-0000000000ff", headers=headers).status_code == 404

    drive_to_delivered(svc)
    proj = projector_registry()
    from edacommon.consumer import MessageProcessor
    from edacommon.consumer.forwarder import Forwarder

    p = MessageProcessor(
        group="order-history-projector",
        registry=proj,
        db=svc.h.db,
        serde=svc.h.serde,
        forwarder=Forwarder(svc.h.producer, "order-history-projector"),
        metrics=svc.h.metrics,
        clock=svc.h.clock,
        sleep=lambda s: None,
    )
    _project(svc, p)
    r = c.get(f"/orders/{ORDER}", headers=headers)
    body = r.json()
    assert body["source"] == "READ_MODEL" and body["status"] == "DELIVERED" and body["invoiceAvailable"] is True
    assert body["shipment"]["trackingNumber"] == "FC1"
    assert [t["kind"] for t in body["timeline"]][:2] == ["ORDER_PLACED", "ORDER_CONFIRMED"]
    validate_response("orders.yaml", "/orders/{orderId}", "get", 200, body)
    etag = r.headers["ETag"]
    assert c.get(f"/orders/{ORDER}", headers={**headers, "If-None-Match": etag}).status_code == 304
    inv = c.get(f"/orders/{ORDER}/invoice", headers=headers)
    assert inv.status_code == 302 and "invoices" in inv.headers["location"]
    lst = c.get("/customers/me/orders", headers=headers)
    assert lst.status_code == 200 and [o["orderId"] for o in lst.json()["items"]] == [ORDER]
    validate_response("orders.yaml", "/customers/me/orders", "get", 200, lst.json())


def _project(svc: Svc, p: Any) -> None:
    from edacommon.consumer import ConsumedRecord

    for i, pub in enumerate(x for x in svc.all if x.topic == "order.events.v1" or x.topic.endswith(".events.v1")):
        data = svc.h.serde.serialize(pub.topic, pub.type, pub.value)
        rec = ConsumedRecord(
            topic=pub.topic,
            partition=0,
            offset=i,
            key=(pub.key or "").encode(),
            value=data,
            headers=[(k, v.encode() if v else None) for k, v in pub.headers.items()],
        )
        assert p.process(rec).outcome in (Outcome.SUCCESS, Outcome.IGNORED)


def test_ops_saga_view_and_retry_step(svc: Svc) -> None:
    c = app(svc)
    svc.send(R.CheckoutSubmitted, checkout_body(), producer="checkout-svc")
    v = c.get(f"/ops/sagas/{ORDER}").json()
    assert v["sagaType"] == "ORDER" and v["state"] == "RESERVING_STOCK" and v["history"][0]["to"] == "RESERVING_STOCK"
    r = c.post(f"/ops/sagas/{ORDER}/retry-step", headers={"Idempotency-Key": "k1"})
    assert r.status_code == 409, "not in NEEDS_ATTENTION: nothing to retry"
    assert c.get("/ops/sagas/missing").status_code == 404
