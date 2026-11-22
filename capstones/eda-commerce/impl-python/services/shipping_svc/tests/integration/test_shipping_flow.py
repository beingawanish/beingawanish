"""shipping-svc with real Postgres, its migrations, the consumer processor, the polling relay, the fake
carrier posting signed webhooks to the real endpoint, and an S3 API (moto) (checklist §11)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheck
from edacommon.consumer import ConsumedRecord, Outcome
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from edacommon.webhooks import sign
from shipping_svc.adapters.outbound.persistence.repositories import TrackingEventStore
from sqlalchemy import create_engine

from .conftest import ADDRESS, ORDER, Svc

pytestmark = pytest.mark.integration


def names(out: list[Any]) -> list[str]:
    return [p.type.rsplit(".", 1)[1] for p in out]


def test_shared_tables_match_contract_and_orm_matches_migrations(svc: Svc) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from shipping_svc.adapters.outbound.persistence.models import Base

    tables = ["outbox", "inbox", "idempotency_key"]
    with fresh_database("contract") as ref:
        e = create_engine(ref)
        with e.begin() as c:
            c.exec_driver_sql(contract_sql_path().read_text())
        e.dispose()
        assert information_schema_columns(svc.h.url, tables) == information_schema_columns(ref, tables)
    e = create_engine(svc.h.url)
    with e.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    e.dispose()
    assert [
        d for d in diff if d[0] in ("add_table", "add_column", "remove_column") and getattr(d[1], "name", "") not in tables
    ] == []


def test_order_packed_books_and_stores_label_then_tracks_to_delivered(svc: Svc) -> None:
    assert svc.packed() is Outcome.SUCCESS
    (created,) = svc.out()
    v = created.value
    assert created.type.endswith("ShipmentCreated") and created.key == ORDER
    assert v["direction"] == "OUTBOUND" and v["fulfilmentId"] == "f-1" and v["carrier"] == "fake-carrier"
    assert created.envelope["producer"] == "shipping-svc" and created.envelope["aggregateType"] == "Shipment"
    cc = ClaimCheck.from_avro(v["label"])
    assert cc.bucket == "shipping-labels" and cc.object_key == f"shipping/2026/11/{ORDER}/{v['shipmentId']}.pdf"
    assert svc.cc.get(cc).startswith(b"%PDF") and cc.expires_at is not None
    out = svc.settle()
    assert names(out) == ["ShipmentInTransit"] * 3 + ["ShipmentDelivered"]
    assert out[-1].value["shipmentId"] == v["shipmentId"] and out[-1].value["returnId"] is None
    assert set(svc.webhook_statuses) == {200}


def test_redelivered_order_packed_reemits_one_shipment(svc: Svc) -> None:
    svc.packed()
    (first,) = svc.out()
    svc.packed()  # new eventId, same fulfilment (relay restart)
    (again,) = svc.out()
    assert again.value["shipmentId"] == first.value["shipmentId"] and svc.carrier.bookings[first.value["shipmentId"]] == 1


def test_out_of_order_and_duplicate_webhooks_yield_monotonic_unique_events(svc: Svc, metrics_reader: Any) -> None:
    svc.carrier.config = svc.carrier.config.merged({"duplicateRate": 1.0, "outOfOrderRate": 1.0})
    svc.packed()
    svc.out()
    out = svc.settle()
    assert names(out).count("ShipmentDelivered") == 1
    statuses = []
    for p in out:
        if p.type.endswith("ShipmentInTransit"):
            statuses.append(p.value["carrierTimestamp"])
    assert statuses == sorted(statuses), "never moves backwards"
    assert len({p.value["carrierEventId"] for p in out}) == len(out), "each event once"
    assert counter_value(metrics_reader[1], "eda.webhook.received", source="carrier", outcome="duplicate") == 4
    with svc.h.db.unit_of_work() as uow:
        hist = TrackingEventStore(uow.session).history(svc.carrier._by_shipment[out[0].value["shipmentId"]].tracking_number)
    assert len(hist) == 4 and all(h.processed_at for h in hist), "every raw webhook stored for audit"


def test_delivered_first_then_late_scans_are_stored_only(svc: Svc) -> None:
    svc.carrier.config = svc.carrier.config.merged({"stepDelayMs": 0})
    svc.packed()
    (created,) = svc.out()
    t = created.value["trackingNumber"]
    r = svc.http.post(f"/admin/fakes/carrier/shipments/{t}/advance", json={"toStatus": "DELIVERED"})
    assert r.status_code == 202
    assert names(svc.settle(force=False)) == ["ShipmentDelivered"]
    svc.carrier.advance(t, "IN_TRANSIT")
    assert svc.settle(force=False) == []
    svc.carrier.advance(t, "EXCEPTION", "DAMAGED")
    (exc,) = svc.settle(force=False)
    assert exc.type.endswith("ShipmentException") and exc.value["code"] == "DAMAGED"
    assert svc.http.post("/admin/fakes/carrier/shipments/NOPE/advance", json={}).status_code == 404
    assert svc.http.post(f"/admin/fakes/carrier/shipments/{t}/advance", json={"toStatus": "LOST"}).status_code == 400


def test_webhook_security_and_validation(svc: Svc, metrics_reader: Any) -> None:
    body = json.dumps(
        {"carrierEventId": "c1", "trackingNumber": "FC1", "status": "IN_TRANSIT", "occurredAt": "2026-11-18T09:10:00Z"}
    ).encode()
    ts = str(int(svc.h.clock.now().timestamp()))
    good = {"X-Webhook-Timestamp": ts, "X-Carrier-Signature": sign(svc.settings.carrier_webhook_secret, ts, body)}
    assert svc.http.post("/webhooks/carrier", content=body, headers={**good, "X-Carrier-Signature": "00"}).status_code == 401
    stale = str(int((svc.h.clock.now() - timedelta(minutes=6)).timestamp()))
    stale_h = {"X-Webhook-Timestamp": stale, "X-Carrier-Signature": sign(svc.settings.carrier_webhook_secret, stale, body)}
    assert svc.http.post("/webhooks/carrier", content=body, headers=stale_h).status_code == 401
    bad = b'{"carrierEventId":"c2","trackingNumber":"FC1","status":"TELEPORTED","occurredAt":"2026-11-18T09:10:00Z"}'
    bad_h = {"X-Webhook-Timestamp": ts, "X-Carrier-Signature": sign(svc.settings.carrier_webhook_secret, ts, bad)}
    assert svc.http.post("/webhooks/carrier", content=bad, headers=bad_h).status_code == 400
    assert svc.http.post("/webhooks/carrier", content=body, headers=good).status_code == 200
    assert svc.http.post("/webhooks/carrier", content=body, headers=good).status_code == 200  # duplicate
    # Unknown tracking number: kept for an hour (the booking may not be committed yet), then orphaned.
    assert svc.w.tracking.run_once() == 0
    svc.h.clock.advance(timedelta(hours=2))
    assert svc.w.tracking.run_once() == 1
    assert counter_value(metrics_reader[1], "eda.webhook.received", source="carrier", outcome="rejected") == 3


def test_booking_failure_retries_on_schedule_then_gives_up_with_exception(svc: Svc) -> None:
    svc.carrier.config = svc.carrier.config.merged({"bookingFailureRate": 1.0})
    svc.packed()
    assert svc.out() == []
    for wait in (10, 60, 600):
        assert svc.w.bookings.run_once() == 0  # not due yet
        svc.h.clock.advance(timedelta(seconds=wait))
        assert svc.w.bookings.run_once() == 1
    svc.h.clock.advance(timedelta(hours=1))
    assert svc.w.bookings.run_once() == 1
    (exc,) = svc.out()
    assert exc.type.endswith("ShipmentException") and exc.value["code"] == "BOOKING_FAILED"


def test_booking_retry_succeeds(svc: Svc) -> None:
    svc.carrier.config = svc.carrier.config.merged({"bookingFailureRate": 1.0})
    svc.packed()
    svc.carrier.config = svc.carrier.config.merged({"bookingFailureRate": 0.0})
    svc.h.clock.advance(timedelta(seconds=10))
    svc.w.bookings.run_once()
    assert names(svc.out()) == ["ShipmentCreated"]


def test_return_label_is_idempotent_and_recovers_after_booking_failed(svc: Svc) -> None:
    body = {"orderId": ORDER, "returnId": "ret-1", "shipmentId": "rs-1", "pickupFrom": ADDRESS, "toWarehouseId": "wh-berlin-1"}

    def issue() -> Outcome:
        return svc.h.deliver(
            svc.registry, svc.h.command(R.IssueReturnLabel, body, key=ORDER, producer="returns-svc", correlation_id="ret-1")
        )

    svc.carrier.config = svc.carrier.config.merged({"bookingFailureRate": 1.0})
    issue()
    for _ in range(4):
        svc.h.clock.advance(timedelta(hours=1))
        svc.w.bookings.run_once()
    (failed,) = svc.out()
    assert failed.value["code"] == "BOOKING_FAILED" and failed.value["direction"] == "RETURN"
    svc.carrier.config = svc.carrier.config.merged({"bookingFailureRate": 0.0})
    assert issue() is Outcome.SUCCESS  # the saga's resend restarts the attempts
    (created,) = svc.out()
    assert (
        created.value["shipmentId"] == "rs-1" and created.value["returnId"] == "ret-1" and created.value["direction"] == "RETURN"
    )
    assert created.envelope["correlationId"] == "ret-1"
    issue()
    assert names(svc.out()) == ["ShipmentCreated"]
    out = svc.settle()
    assert (
        out[-1].type.endswith("ShipmentDelivered")
        and out[-1].value["returnId"] == "ret-1"
        and out[-1].value["direction"] == "RETURN"
    )


def test_unknown_type_is_ignored(svc: Svc) -> None:
    rec = ConsumedRecord(
        topic="fulfilment.events.v1",
        partition=0,
        offset=1,
        key=b"o",
        value=b"??",
        headers=[("ce_type", b"com.edacommerce.fulfilment.OrderPicked"), ("ce_id", b"x")],
    )
    assert svc.h.deliver(svc.registry, rec) is Outcome.IGNORED


def test_fake_carrier_admin_config(svc: Svc) -> None:
    r = svc.http.put("/admin/fakes/carrier", json={"duplicateRate": 0.5, "stepDelayMs": 5})
    assert r.status_code == 200 and r.json()["duplicateRate"] == 0.5 and svc.carrier.config.stepDelayMs == 5
    assert svc.http.put("/admin/fakes/carrier", json={"exceptionRate": 3}).status_code == 400
