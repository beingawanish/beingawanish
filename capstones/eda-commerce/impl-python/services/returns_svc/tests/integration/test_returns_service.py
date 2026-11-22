"""returns-svc with real Postgres, its migrations, the consumer processor, the saga kit, the deadline
sweeper, the polling relay, the Returns API and an S3 API (moto) (checklist §11 returns items)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from contracts_py import records as R
from edacommon.consumer import Outcome
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from edacommon.testing.openapi import validate_response
from sqlalchemy import create_engine

from .conftest import ORDER, Svc

pytestmark = pytest.mark.integration


def names(out: list[Any]) -> list[str]:
    return [p.type.rsplit(".", 1)[1] for p in out]


def settle(svc: Svc, rid: str) -> None:
    rs = svc.last("RestockItems")
    rf = svc.last("RefundPayment")
    svc.send(
        R.ItemsRestocked,
        {"orderId": ORDER, "returnId": rid, "restockId": rs["restockId"], "lines": rs["lines"], "restockedAt": svc.h.clock.now()},
        producer="inventory-svc",
    )
    svc.send(
        R.RefundSucceeded,
        {
            "orderId": ORDER,
            "paymentId": "pay-1",
            "refundId": rf["refundId"],
            "amount": rf["amount"],
            "pspReference": "psp",
            "refundedAt": svc.h.clock.now(),
            "returnId": rid,
        },
        producer="payment-svc",
    )
    svc.out()


def test_shared_tables_match_contract_and_orm_matches_migrations(svc: Svc) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from returns_svc.adapters.outbound.persistence.models import Base

    tables = ["outbox", "inbox", "idempotency_key", "saga_instance", "saga_transition"]
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


def test_full_return_runs_to_refunded_with_line_totals(svc: Svc, metrics_reader: Any) -> None:
    svc.deliver_order()
    r = svc.post_return([("l-1", 2)], key="ret-key")
    assert r.status_code == 202, r.text
    body = r.json()
    validate_response("returns.yaml", "/returns", "post", 202, body)
    rid = body["returnId"]
    assert r.headers["Location"] == f"/returns/{rid}" and body["status"] == "AWAITING_PARCEL"
    assert body["rmaNumber"] == "RMA-2026-000001" and body["labelAvailable"] is False
    out = svc.out()
    assert names(out) == ["ReturnRequested", "ReturnAuthorized", "IssueReturnLabel", "ExpectReturn"]
    for p in out:
        assert p.key == ORDER and p.envelope["correlationId"] == rid and p.envelope["producer"] == "returns-svc"
        assert p.envelope["aggregateType"] == "Return" and p.envelope["aggregateId"] == rid
    assert [p.envelope["aggregateVersion"] for p in out[:2]] == [1, 2]
    assert out[2].value["pickupFrom"]["city"] == "Berlin" and out[2].value["toWarehouseId"] == "wh-berlin-1"
    assert out[3].value["rmaNumber"] == "RMA-2026-000001"
    replay = svc.post_return([("l-1", 2)], key="ret-key")
    assert replay.json()["returnId"] == rid and replay.headers.get("Idempotent-Replayed") == "true"

    svc.label(rid)
    svc.out()
    got = svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()
    assert got["labelAvailable"] is True
    lab = svc.http.get(f"/returns/{rid}/label", headers={"X-Debug-Subject": "cust-1"})
    assert lab.status_code == 302 and "shipping-labels" in lab.headers["Location"]

    svc.inspect(rid, [(2, "RESTOCKABLE")])
    rf = svc.last("RefundPayment")
    assert rf["refundId"] and rf["paymentId"] == "pay-1" and rf["amount"] == {"amountMinor": 25998, "currency": "EUR"}
    assert rf["returnId"] == rid
    assert svc.last("RestockItems")["lines"] == [{"sku": "SKU-1001", "quantity": 2}]
    assert svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()["status"] == "REFUNDING"
    settle(svc, rid)
    assert names(svc.all[-2:]) == ["ReturnRefunded", "ReturnClosed"] and svc.last("ReturnClosed")["outcome"] == "REFUNDED"
    final = svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()
    validate_response("returns.yaml", "/returns/{returnId}", "get", 200, final)
    assert final["status"] == "REFUNDED" and final["refundAmount"] == {"amountMinor": 25998, "currency": "EUR"}
    assert final["lines"][0]["inspectionOutcome"] == "RESTOCKABLE"
    saga = svc.http.get(f"/ops/sagas/{rid}").json()
    validate_response("admin.yaml", "/ops/sagas/{sagaId}", "get", 200, saga)
    assert [h["to"] for h in saga["history"]] == [
        "REQUESTED",
        "AUTHORIZED",
        "AWAITING_PARCEL",
        "AWAITING_PARCEL",
        "AWAITING_INSPECTION",
        "SETTLING",
        "SETTLING",
        "CLOSED",
    ]
    assert counter_value(metrics_reader[1], "eda.saga.outcomes", saga_type="RETURN", outcome="REFUNDED") == 1


def test_damaged_item_with_changed_mind_ends_partially_refunded(svc: Svc) -> None:
    svc.deliver_order()
    rid = svc.post_return([("l-1", 2)]).json()["returnId"]
    svc.out()
    svc.inspect(rid, [(1, "RESTOCKABLE"), (1, "DAMAGED")])
    assert svc.last("RefundPayment")["amount"]["amountMinor"] == 12999
    assert svc.last("RestockItems")["lines"] == [{"sku": "SKU-1001", "quantity": 1}]
    settle(svc, rid)
    assert svc.last("ReturnClosed")["outcome"] == "PARTIALLY_REFUNDED"
    body = svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()
    assert body["status"] == "PARTIALLY_REFUNDED" and body["lines"][0]["inspectionOutcome"] == "DAMAGED"


def test_merchant_fault_refunds_the_shipping_fee_on_the_first_return_only(svc: Svc) -> None:
    svc.deliver_order(fee=499)
    r1 = svc.post_return([("l-1", 1)], "WRONG_ITEM").json()["returnId"]
    svc.out()
    svc.inspect(r1, [(1, "DAMAGED")])
    assert svc.last("RefundPayment")["amount"]["amountMinor"] == 12999 + 499
    r2 = svc.post_return([("l-1", 1)], "WRONG_ITEM").json()["returnId"]
    svc.out()
    svc.inspect(r2, [(1, "RESTOCKABLE")])
    assert svc.last("RefundPayment")["amount"]["amountMinor"] == 12999


def test_eligibility_problems(svc: Svc) -> None:
    def ptype(r: Any) -> str:
        assert r.status_code == 422, r.text
        return str(r.json()["type"]).rsplit("/", 1)[1]

    svc.send(
        R.OrderPlaced,
        {
            "orderId": ORDER,
            "customerId": "cust-1",
            "lines": [
                {
                    "lineId": "l-1",
                    "sku": "SKU-1001",
                    "productName": "x",
                    "quantity": 2,
                    "unitPrice": {"amountMinor": 100, "currency": "EUR"},
                    "lineTotal": {"amountMinor": 200, "currency": "EUR"},
                }
            ],
            "total": {"amountMinor": 200, "currency": "EUR"},
            "shippingAddress": {"recipientName": "J", "line1": "x", "city": "B", "postalCode": "1", "countryCode": "DE"},
            "contactEmail": "j@example.com",
            "shippingMethod": "STANDARD",
            "placedAt": svc.h.clock.now(),
        },
        producer="order-svc",
    )
    assert ptype(svc.post_return([("l-1", 1)])) == "order-not-delivered"
    svc.deliver_order(delivered_days_ago=31)
    assert ptype(svc.post_return([("l-1", 1)])) == "return-window-closed"
    svc.send(
        R.OrderDelivered,
        {"orderId": ORDER, "shipmentId": "s", "deliveredAt": svc.h.clock.now(), "returnWindowEndsAt": svc.h.clock.now()},
        producer="order-svc",
    )
    assert svc.post_return([("l-1", 1)]).status_code == 202
    assert ptype(svc.post_return([("l-1", 2)])) == "return-quantity-exceeded"
    assert ptype(svc.post_return([("l-9", 1)])) == "unknown-order-line"
    assert svc.post_return([("l-1", 1)], subject="someone-else").status_code == 404
    assert svc.post_return([("l-1", 0)]).status_code == 400
    bad = svc.http.post(
        "/returns", json={"orderId": ORDER, "lines": [{"lineId": "l-1", "quantity": 1}], "reason": "CHANGED_MIND"}
    )
    assert bad.status_code == 400, "Idempotency-Key is required"
    listing = svc.http.get(f"/orders/{ORDER}/returns", headers={"X-Debug-Subject": "cust-1"}).json()
    validate_response("returns.yaml", "/orders/{orderId}/returns", "get", 200, listing)
    assert listing["returnable"] == [{"lineId": "l-1", "sku": "SKU-1001", "quantity": 1}] and len(listing["returns"]) == 1
    assert svc.http.get("/orders/nope/returns").status_code == 404


def test_high_value_waits_for_manual_review_and_decision(svc: Svc, metrics_reader: Any) -> None:
    svc.deliver_order(qty=4, unit=20000)
    body = svc.post_return([("l-1", 4)]).json()
    rid = body["returnId"]
    assert body["status"] == "MANUAL_REVIEW" and body["rmaNumber"] is None
    assert names(svc.out()) == ["ReturnRequested"]
    assert counter_value(metrics_reader[1], "eda.saga.outcomes", saga_type="RETURN", outcome="MANUAL_REVIEW") == 1
    bad = svc.http.post(f"/ops/returns/{rid}/decision", json={"decision": "RETRY_REFUND"}, headers={"Idempotency-Key": "d0"})
    assert bad.status_code == 409
    ok = svc.http.post(
        f"/ops/returns/{rid}/decision", json={"decision": "APPROVE", "note": "loyal customer"}, headers={"Idempotency-Key": "d1"}
    )
    assert ok.status_code == 202 and ok.json()["status"] == "AWAITING_PARCEL"
    validate_response("returns.yaml", "/ops/returns/{returnId}/decision", "post", 202, ok.json())
    assert names(svc.out()) == ["ReturnAuthorized", "IssueReturnLabel", "ExpectReturn"]
    assert (
        svc.http.post("/ops/returns/nope/decision", json={"decision": "APPROVE"}, headers={"Idempotency-Key": "d2"}).status_code
        == 404
    )
    shopper = svc.http.post(
        f"/ops/returns/{rid}/decision",
        json={"decision": "APPROVE"},
        headers={"Idempotency-Key": "d3", "X-Debug-Subject": "cust-1"},
    )
    assert shopper.status_code == 403


def test_refund_failures_follow_the_schedule_then_review_and_retry_refund(svc: Svc) -> None:
    svc.deliver_order()
    rid = svc.post_return([("l-1", 2)]).json()["returnId"]
    svc.out()
    svc.inspect(rid, [(2, "RESTOCKABLE")])
    rs = svc.last("RestockItems")
    svc.send(
        R.ItemsRestocked,
        {"orderId": ORDER, "returnId": rid, "restockId": rs["restockId"], "lines": rs["lines"], "restockedAt": svc.h.clock.now()},
    )
    refund_id = svc.last("RefundPayment")["refundId"]

    def fail() -> None:
        svc.send(
            R.RefundFailed,
            {
                "orderId": ORDER,
                "paymentId": "pay-1",
                "refundId": refund_id,
                "reason": "processing_error",
                "retryable": True,
                "failedAt": svc.h.clock.now(),
                "returnId": None,
            },
        )

    for wait in (timedelta(minutes=1), timedelta(minutes=10), timedelta(hours=1)):
        fail()
        svc.out()
        svc.h.clock.advance(wait - timedelta(seconds=1))
        svc.sweeper.run_once()
        assert "RefundPayment" not in names(svc.out())
        svc.h.clock.advance(timedelta(seconds=1))
        svc.sweeper.run_once()
        (resend,) = [p for p in svc.out() if p.type.endswith("RefundPayment")]
        assert resend.value["refundId"] == refund_id, "the same refundId on every attempt"
    fail()
    svc.out()
    assert svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()["status"] == "MANUAL_REVIEW"
    r = svc.http.post(f"/ops/returns/{rid}/decision", json={"decision": "RETRY_REFUND"}, headers={"Idempotency-Key": "rr"})
    assert r.status_code == 202 and r.json()["status"] == "REFUNDING"
    assert [p.value["refundId"] for p in svc.out() if p.type.endswith("RefundPayment")] == [refund_id]
    svc.send(
        R.RefundSucceeded,
        {
            "orderId": ORDER,
            "paymentId": "pay-1",
            "refundId": refund_id,
            "amount": {"amountMinor": 25998, "currency": "EUR"},
            "pspReference": "p",
            "refundedAt": svc.h.clock.now(),
        },
    )
    svc.out()
    assert svc.last("ReturnClosed")["outcome"] == "REFUNDED"


def test_parcel_never_arrives_expires_and_quantity_is_returnable_again(svc: Svc) -> None:
    svc.deliver_order()
    rid = svc.post_return([("l-1", 2)]).json()["returnId"]
    svc.out()
    svc.label(rid)
    svc.h.clock.advance(timedelta(days=14))
    assert svc.sweeper.run_once() == 1
    assert names(svc.out()) == ["ReturnClosed"] and svc.last("ReturnClosed")["outcome"] == "EXPIRED"
    assert svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()["status"] == "EXPIRED"
    svc.h.clock.set(svc.h.clock.now() - timedelta(days=14))
    assert svc.post_return([("l-1", 2)]).status_code == 202


def test_label_timeout_resends_and_duplicates_are_absorbed(svc: Svc, metrics_reader: Any) -> None:
    svc.deliver_order()
    rid = svc.post_return([("l-1", 1)]).json()["returnId"]
    first = next(p for p in svc.out() if p.type.endswith("IssueReturnLabel"))
    svc.h.clock.advance(timedelta(minutes=10))
    svc.sweeper.run_once()
    resend = [p for p in svc.out() if p.type.endswith("IssueReturnLabel")]
    assert resend[0].value["shipmentId"] == first.value["shipmentId"]
    rec = svc.h.command(R.ReturnReceived, {"orderId": ORDER, "returnId": rid, "receivedAt": svc.h.clock.now()}, key=ORDER)
    assert svc.h.deliver(svc.registry, rec) is Outcome.SUCCESS
    assert svc.h.deliver(svc.registry, rec) is Outcome.DUPLICATE
    assert svc.send(R.ReturnReceived, {"orderId": ORDER, "returnId": rid, "receivedAt": svc.h.clock.now()}) is Outcome.SUCCESS
    assert svc.http.get(f"/returns/{rid}", headers={"X-Debug-Subject": "cust-1"}).json()["status"] == "RECEIVED"
    assert (
        svc.send(R.ReturnReceived, {"orderId": ORDER, "returnId": "unknown", "receivedAt": svc.h.clock.now()}) is Outcome.SUCCESS
    )


def test_retry_step_and_rma_numbers_are_gapless(svc: Svc) -> None:
    svc.deliver_order(qty=3)
    a = svc.post_return([("l-1", 1)]).json()
    b = svc.post_return([("l-1", 1)]).json()
    assert [a["rmaNumber"], b["rmaNumber"]] == ["RMA-2026-000001", "RMA-2026-000002"]
    svc.out()
    r = svc.http.post(f"/ops/sagas/{a['returnId']}/retry-step", headers={"Idempotency-Key": "rs"})
    assert r.status_code == 202 and names(svc.out()) == ["IssueReturnLabel", "ExpectReturn"]
    svc.deliver_order(qty=3)  # replay of order events into the view is harmless
    assert svc.post_return([("l-1", 2)]).status_code == 422


def test_order_events_for_unknown_orders_are_ignored(svc: Svc) -> None:
    assert (
        svc.send(
            R.OrderConfirmed,
            {"orderId": "other", "reservationId": "r", "paymentId": "p", "fulfilmentId": "f", "confirmedAt": svc.h.clock.now()},
        )
        is Outcome.SUCCESS
    )
