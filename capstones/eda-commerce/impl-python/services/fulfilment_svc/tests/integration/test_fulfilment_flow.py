"""fulfilment-svc with real Postgres, its migrations, the consumer processor, the polling relay, the
fake WMS on a manual clock and an S3 API (moto) (checklist §11 layer 3 + fulfilment items)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheck
from edacommon.consumer import ConsumedRecord, Outcome
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from fastapi.testclient import TestClient
from fulfilment_svc.adapters.inbound.http.routes import fake_wms_router
from sqlalchemy import create_engine

from .conftest import ORDER, Svc

pytestmark = pytest.mark.integration


def label() -> dict[str, Any]:
    return {"bucket": "shipping-labels", "objectKey": "k", "contentType": "application/pdf", "sizeBytes": 1, "sha256": "0" * 64}


def shipment_created(svc: Svc, fid: str = "f-1", direction: str = "OUTBOUND", **kw: Any) -> Outcome:
    body = {
        "orderId": ORDER,
        "shipmentId": "ship-1",
        "direction": direction,
        "carrier": "fake-carrier",
        "trackingNumber": "FC1",
        "label": label(),
        "createdAt": svc.h.clock.now(),
        "fulfilmentId": fid,
        **kw,
    }
    return svc.send(R.ShipmentCreated, body, producer="shipping-svc")[1]


def to_packed(svc: Svc) -> list[Any]:
    svc.request()
    svc.advance(1)
    svc.advance(1)
    svc.advance(1)
    return svc.out()


def test_shared_tables_match_contract_and_orm_matches_migrations(svc: Svc) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from fulfilment_svc.adapters.outbound.persistence.models import Base

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
    relevant = [
        d for d in diff if d[0] in ("add_table", "add_column", "remove_column") and getattr(d[1], "name", "") not in tables
    ]
    assert relevant == []


def test_request_to_packed_with_manifest_claim_check(svc: Svc) -> None:
    rec = svc.request()
    assert svc.out() == [], "no reply until the warehouse acknowledges"
    assert svc.advance(1) == 1
    (acc,) = svc.out()
    assert acc.type == "com.edacommerce.fulfilment.FulfilmentAccepted" and acc.key == ORDER
    env = acc.envelope
    assert env["producer"] == "fulfilment-svc" and env["partitionKey"] == ORDER and env["aggregateType"] == "Fulfilment"
    assert env["causationId"] == rec.event_id and env["correlationId"] == ORDER, "async reply keeps the command's causation"
    assert acc.value["warehouseId"] == "wh-berlin-1"
    svc.advance(1)
    (picked,) = svc.out()
    assert picked.type.endswith("OrderPicked")
    svc.advance(1)
    (packed,) = svc.out()
    assert packed.type.endswith("OrderPacked") and packed.value["shipTo"]["city"] == "Berlin"
    assert packed.envelope["aggregateVersion"] == 4
    # Manifest uploaded before the event; the event stays small (README Day 6 acceptance: < 2 KB).
    raw = svc.h.producer.on("fulfilment.events.v1")[-1].value
    assert raw is not None and len(raw) < 2048
    cc = ClaimCheck.from_avro(packed.value["manifest"])
    assert cc.bucket == "packing-manifests" and cc.size_bytes > 256_000
    assert cc.object_key == f"fulfilment/2026/11/{ORDER}/f-1.json" and cc.expires_at is not None
    body = svc.cc.get(cc)  # a consumer verifies size and SHA-256
    assert len(json.loads(body)["scans"]) == 2000
    assert len(packed.value["parcels"]) == 1


def test_dropped_request_recovered_by_resend_with_no_duplicate_pick_order(svc: Svc) -> None:
    svc.wms.config = svc.wms.config.merged({"dropRequestRate": 1.0})
    svc.request(attempt=1)
    assert svc.advance(600) == 0 and svc.out() == []  # lost by the warehouse
    svc.wms.config = svc.wms.config.merged({"dropRequestRate": 0.0})
    svc.request(attempt=2)  # the saga's deadline resend (new eventId, same fulfilmentId)
    svc.advance(1)
    (acc,) = svc.out()
    assert acc.type.endswith("FulfilmentAccepted")
    svc.request(attempt=3)  # a late third resend: original reply, still one pick order
    svc.advance(0)
    out = svc.out()
    assert [p.type.rsplit(".", 1)[1] for p in out] == ["FulfilmentAccepted"]
    assert out[0].value["acceptedAt"] == acc.value["acceptedAt"]
    assert svc.wms.pick_orders("f-1") == 1 and svc.wms.submissions["f-1"] == 2


def test_duplicate_delivery_has_one_effect(svc: Svc, metrics_reader: Any) -> None:
    rec = svc.request()
    assert svc.h.deliver(svc.registry, rec) is Outcome.DUPLICATE
    assert svc.wms.submissions["f-1"] == 1
    assert counter_value(metrics_reader[1], "eda.consumer.processed", outcome="duplicate") == 1


def test_shipment_created_dispatches_and_return_shipments_are_ignored(svc: Svc) -> None:
    to_packed(svc)
    assert shipment_created(svc, direction="RETURN", returnId="ret-1") is Outcome.SUCCESS
    assert svc.out() == []
    assert shipment_created(svc) is Outcome.SUCCESS
    (d,) = svc.out()
    assert d.type.endswith("OrderDispatched") and d.value["shipmentId"] == "ship-1"
    assert shipment_created(svc) is Outcome.SUCCESS  # re-emitted booking: same fact again
    (again,) = svc.out()
    assert again.value["dispatchedAt"] == d.value["dispatchedAt"]
    assert shipment_created(svc, direction="UNKNOWN") is Outcome.SUCCESS  # enum UNKNOWN handled


def test_cancel_before_accept_stops_the_warehouse_and_late_progress_is_ignored(svc: Svc) -> None:
    svc.request()
    _, outcome = svc.send(R.CancelFulfilment, {"orderId": ORDER, "fulfilmentId": "f-1", "reason": "PAYMENT_DECLINED"})
    assert outcome is Outcome.SUCCESS
    (c,) = svc.out()
    assert c.type.endswith("FulfilmentCancelled")
    assert svc.advance(10) == 0 and svc.out() == []
    svc.request(attempt=2)  # late resend
    assert [p.type.rsplit(".", 1)[1] for p in svc.out()] == ["FulfilmentCancelled"]


def test_cancel_unknown_tombstones_so_a_late_request_never_starts_picking(svc: Svc) -> None:
    svc.send(R.CancelFulfilment, {"orderId": ORDER, "fulfilmentId": "f-9", "reason": "SAGA_TIMEOUT"})
    svc.request("f-9")
    assert [p.type.rsplit(".", 1)[1] for p in svc.out()] == ["FulfilmentCancelled", "FulfilmentCancelled"]
    assert svc.wms.submissions["f-9"] == 0


def test_cancel_after_dispatch_goes_to_the_dlq(svc: Svc) -> None:
    to_packed(svc)
    shipment_created(svc)
    svc.out()
    _, outcome = svc.send(R.CancelFulfilment, {"orderId": ORDER, "fulfilmentId": "f-1", "reason": "x"})
    assert outcome is Outcome.DLQ
    assert svc.h.producer.on("fulfilment-svc.dlq")


def test_warehouse_failure_emits_fulfilment_failed(svc: Svc) -> None:
    svc.wms.config = svc.wms.config.merged({"failRate": 1.0})
    svc.request()
    svc.advance(1)
    svc.advance(1)
    svc.advance(1)
    types = [p.type.rsplit(".", 1)[1] for p in svc.out()]
    assert types == ["FulfilmentAccepted", "OrderPicked", "FulfilmentFailed"]


def test_object_store_outage_keeps_the_event_until_the_upload_succeeds(svc: Svc) -> None:
    svc.request()
    svc.advance(1)
    svc.advance(1)
    svc.out()
    svc.s3.delete_bucket(Bucket="packing-manifests")  # upload fails -> nothing committed, not acked
    assert svc.advance(1) == 0
    assert svc.out() == []
    svc.s3.create_bucket(Bucket="packing-manifests")
    assert svc.advance(0) == 1
    (packed,) = svc.out()
    svc.cc.get(ClaimCheck.from_avro(packed.value["manifest"]))  # no event points at a missing object


def test_returns_intake_received_then_inspected(svc: Svc) -> None:
    svc.wms.config = svc.wms.config.merged({"inspectionDamagedRate": 0.0})
    delivered = {
        "orderId": ORDER,
        "shipmentId": "rs-1",
        "direction": "RETURN",
        "carrierEventId": "c9",
        "deliveredAt": svc.h.clock.now(),
        "returnId": "ret-1",
    }
    # Delivered before ExpectReturn (another topic): wait on the retry topics.
    assert svc.send(R.ShipmentDelivered, delivered, producer="shipping-svc")[1] is Outcome.RETRY
    expect = {
        "orderId": ORDER,
        "returnId": "ret-1",
        "rmaNumber": "RMA-2026-000042",
        "lines": [{"lineId": "l-1", "sku": "SKU-1001", "quantity": 2}],
        "expectedBy": svc.h.clock.now(),
    }
    svc.send(R.ExpectReturn, expect, producer="returns-svc")
    svc.send(R.ExpectReturn, expect, producer="returns-svc")  # resend: no-op
    rec, outcome = svc.send(R.ShipmentDelivered, delivered, producer="shipping-svc")
    assert outcome is Outcome.SUCCESS
    (rcv,) = svc.out()
    assert rcv.type.endswith("ReturnReceived") and rcv.value["returnId"] == "ret-1"
    svc.advance(1)
    (insp,) = svc.out()
    assert insp.type.endswith("ReturnInspected")
    assert insp.value["results"] == [{"lineId": "l-1", "sku": "SKU-1001", "quantity": 2, "outcome": "RESTOCKABLE", "note": None}]
    assert insp.envelope["causationId"] == rec.event_id
    svc.send(R.ShipmentDelivered, delivered, producer="shipping-svc", event_id=None)  # duplicate fact: no-op
    assert svc.out() == []
    svc.send(R.ShipmentDelivered, {**delivered, "direction": "OUTBOUND"}, producer="shipping-svc")
    assert svc.out() == []


def test_unknown_type_is_ignored(svc: Svc) -> None:
    rec = ConsumedRecord(
        topic="fulfilment.commands.v1",
        partition=0,
        offset=1,
        key=b"o",
        value=b"??",
        headers=[("ce_type", b"com.edacommerce.fulfilment.SplitShipment"), ("ce_id", b"x1")],
    )
    assert svc.h.deliver(svc.registry, rec) is Outcome.IGNORED


def test_fake_wms_admin_api(svc: Svc) -> None:
    app = create_app(svc.settings, readiness=Readiness(), instrument=False, routers=[fake_wms_router(svc.wms, Authenticator(svc.settings))])
    c = TestClient(app)
    r = c.put("/admin/fakes/wms", json={"dropRequestRate": 0.5, "manifestLines": 10})
    assert r.status_code == 200 and r.json()["dropRequestRate"] == 0.5 and svc.wms.config.manifestLines == 10
    assert c.put("/admin/fakes/wms", json={"failRate": 2}).status_code == 400
    assert c.put("/admin/fakes/wms", json={"pickDelayMs": -1}).status_code == 400
