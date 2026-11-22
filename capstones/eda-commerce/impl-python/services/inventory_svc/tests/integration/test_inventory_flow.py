"""inventory-svc with real Postgres, its own migrations, the consumer processor and the polling
relay (checklist §11 layer 3 + inventory-specific items)."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from contracts_py.records import CommitReservation, ReleaseReservation, ReserveStock, RestockItems
from edacommon.consumer import Outcome
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from inventory_svc.adapters.inbound.jobs.expiry import ExpirySweeper
from sqlalchemy import create_engine

from .conftest import Svc

pytestmark = pytest.mark.integration
ORDER = "0193a1c4-0000-7000-8000-00000000a001"


def reserve(
    svc: Svc, rid: str, lines: list[tuple[str, int]], *, order: str = ORDER, ttl: int = 900, event_id: str | None = None
) -> Any:
    return svc.h.command(
        ReserveStock,
        {"orderId": order, "reservationId": rid, "ttlSeconds": ttl, "lines": [{"sku": s, "quantity": q} for s, q in lines]},
        key=order,
        event_id=event_id,
    )


def test_migrations_create_contract_shared_tables_and_private_tables(svc: Svc) -> None:
    tables = ["outbox", "inbox", "idempotency_key"]
    with fresh_database("contract") as ref:
        e = create_engine(ref)
        with e.begin() as c:
            c.exec_driver_sql(contract_sql_path().read_text())
        e.dispose()
        assert information_schema_columns(svc.h.url, tables) == information_schema_columns(ref, tables)
    cols = {r[0] for r in information_schema_columns(svc.h.url, ["stock", "reservation", "reservation_line", "restock"])}
    assert cols == {"stock", "reservation", "reservation_line", "restock"}


def test_orm_models_match_migrated_schema(svc: Svc) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from inventory_svc.adapters.outbound.persistence.models import Base

    e = create_engine(svc.h.url)
    with e.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    e.dispose()
    # Only differences that matter: missing/extra tables or columns. (CHECKs/indexes live in SQL.)
    relevant = [
        d
        for d in diff
        if d[0] in ("add_table", "add_column", "remove_column")
        and getattr(d[1], "name", "") not in ("outbox", "inbox", "idempotency_key")
    ]
    assert relevant == []


def test_reserve_command_in_reply_out_with_db_state_and_envelope(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 50)
    svc.h.published()
    rec = reserve(svc, "r-1", [("SKU-1001", 2)])
    assert svc.h.deliver(svc.registry, rec) is Outcome.SUCCESS
    out = svc.h.published()
    reply = next(p for p in out if p.type.endswith("StockReserved"))
    assert reply.topic == "inventory.events.v1" and reply.key == ORDER
    assert reply.value["reservationId"] == "r-1" and reply.value["lines"] == [{"sku": "SKU-1001", "quantity": 2}]
    env = reply.envelope
    assert env["type"] == "com.edacommerce.inventory.StockReserved" and env["producer"] == "inventory-svc"
    assert env["partitionKey"] == ORDER and env["causationId"] == rec.event_id and env["correlationId"] == ORDER
    assert env["aggregateType"] == "Reservation" and env["aggregateId"] == "r-1"
    level = next(p for p in out if p.type.endswith("StockLevelChanged"))
    assert level.topic == "inventory.stock-level.v1" and level.key == "SKU-1001"
    assert (level.value["onHand"], level.value["reserved"], level.value["available"]) == (50, 2, 48)
    lv = svc.level("SKU-1001")
    assert (lv.on_hand, lv.reserved) == (50, 2)


def test_duplicate_delivery_one_effect_one_reply(svc: Svc, metrics_reader: Any) -> None:
    svc.set_stock("SKU-1001", 50)
    svc.h.published()
    rec = reserve(svc, "r-1", [("SKU-1001", 2)])
    assert svc.h.deliver(svc.registry, rec) is Outcome.SUCCESS
    assert svc.h.deliver(svc.registry, rec) is Outcome.DUPLICATE
    replies = [p for p in svc.h.published() if p.type.endswith("StockReserved")]
    assert len(replies) == 1 and svc.level("SKU-1001").reserved == 2
    assert counter_value(metrics_reader[1], "eda.consumer.processed", outcome="duplicate") == 1


def test_resent_command_reemits_original_reply_without_repeating_effect(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 50)
    svc.h.deliver(svc.registry, reserve(svc, "r-1", [("SKU-1001", 2)]))
    first = next(p for p in svc.h.published() if p.type.endswith("StockReserved"))
    resend = reserve(svc, "r-1", [("SKU-1001", 2)])  # new eventId, same reservationId (saga resend)
    assert svc.h.deliver(svc.registry, resend) is Outcome.SUCCESS
    again = [p for p in svc.h.published() if p.type.endswith("StockReserved")]
    assert len(again) == 1 and again[0].value["expiresAt"] == first.value["expiresAt"]
    assert again[0].envelope["causationId"] == resend.event_id
    assert svc.level("SKU-1001").reserved == 2, "no second hold"


def test_all_or_nothing_and_rejection_with_shortages(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 50)
    svc.set_stock("SKU-1006", 0)
    svc.h.published()
    svc.h.deliver(svc.registry, reserve(svc, "r-2", [("SKU-1001", 1), ("SKU-1006", 1), ("SKU-404", 1)]))
    (rej,) = [p for p in svc.h.published() if p.type.endswith("StockReservationRejected")]
    assert rej.value["shortages"] == [
        {"sku": "SKU-1006", "requested": 1, "available": 0},
        {"sku": "SKU-404", "requested": 1, "available": 0},
    ]
    assert svc.level("SKU-1001").reserved == 0, "no partial hold"
    svc.h.deliver(svc.registry, reserve(svc, "r-2", [("SKU-1001", 1)]))  # resend: same answer
    assert [p.type for p in svc.h.published()] == ["com.edacommerce.inventory.StockReservationRejected"]


def test_two_concurrent_reservations_for_the_last_unit_exactly_one_wins(svc: Svc) -> None:
    svc.set_stock("SKU-1005", 1)
    svc.h.published()
    recs = [reserve(svc, f"r-{i}", [("SKU-1005", 1)], order=f"o-{i}") for i in range(2)]
    barrier = threading.Barrier(2)
    outcomes: list[Any] = []

    def go(r: Any) -> None:
        barrier.wait()
        outcomes.append(svc.h.deliver(svc.registry, r))

    threads = [threading.Thread(target=go, args=(r,)) for r in recs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes == [Outcome.SUCCESS, Outcome.SUCCESS]
    types = sorted(p.type.rsplit(".", 1)[1] for p in svc.h.published() if p.topic == "inventory.events.v1")
    assert types == ["StockReservationRejected", "StockReserved"]
    lv = svc.level("SKU-1005")
    assert (lv.on_hand, lv.reserved) == (1, 1)


def test_ttl_expiry_emits_expired_restores_stock_and_late_commit_answers_expired(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    svc.h.deliver(svc.registry, reserve(svc, "r-3", [("SKU-1001", 4)], ttl=60))
    svc.h.published()
    sweeper = ExpirySweeper(svc.h.db, svc.inventory_for, svc.h.clock)
    assert sweeper.run_once() == 0
    svc.h.clock.advance(timedelta(seconds=61))
    assert sweeper.run_once() == 1
    out = svc.h.published()
    (exp,) = [p for p in out if p.type.endswith("ReservationExpired")]
    assert exp.value["reservationId"] == "r-3" and exp.envelope["causationId"] is None  # timer-caused
    (lvl,) = [p for p in out if p.type.endswith("StockLevelChanged")]
    assert lvl.value["available"] == 10
    svc.h.deliver(svc.registry, svc.h.command(CommitReservation, {"orderId": ORDER, "reservationId": "r-3"}, key=ORDER))
    assert [p.type for p in svc.h.published()] == ["com.edacommerce.inventory.ReservationExpired"]
    assert svc.level("SKU-1001").reserved == 0


def test_commit_past_ttl_before_sweeper_still_answers_expired(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    svc.h.deliver(svc.registry, reserve(svc, "r-4", [("SKU-1001", 4)], ttl=60))
    svc.h.published()
    svc.h.clock.advance(timedelta(seconds=120))
    svc.h.deliver(svc.registry, svc.h.command(CommitReservation, {"orderId": ORDER, "reservationId": "r-4"}, key=ORDER))
    assert "com.edacommerce.inventory.ReservationExpired" in [p.type for p in svc.h.published()]
    assert svc.level("SKU-1001").reserved == 0


def test_commit_then_release_returns_allocated_units_and_release_twice_is_noop(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    svc.h.deliver(svc.registry, reserve(svc, "r-5", [("SKU-1001", 3)]))
    svc.h.deliver(svc.registry, svc.h.command(CommitReservation, {"orderId": ORDER, "reservationId": "r-5"}, key=ORDER))
    lv = svc.level("SKU-1001")
    assert (lv.on_hand, lv.reserved) == (7, 0)
    svc.h.published()
    for _ in range(2):
        svc.h.deliver(
            svc.registry,
            svc.h.command(
                ReleaseReservation, {"orderId": ORDER, "reservationId": "r-5", "reason": "PAYMENT_DECLINED"}, key=ORDER
            ),
        )
    released = [p for p in svc.h.published() if p.type.endswith("ReservationReleased")]
    assert len(released) == 2 and released[0].value["releasedAt"] == released[1].value["releasedAt"]
    assert svc.level("SKU-1001").on_hand == 10


def test_release_before_reserve_tombstones_the_reservation(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    svc.h.deliver(
        svc.registry,
        svc.h.command(ReleaseReservation, {"orderId": ORDER, "reservationId": "r-6", "reason": "SAGA_TIMEOUT"}, key=ORDER),
    )
    svc.h.deliver(svc.registry, reserve(svc, "r-6", [("SKU-1001", 1)]))  # late, via a retry topic
    types = [p.type for p in svc.h.published() if p.topic == "inventory.events.v1"]
    assert types == ["com.edacommerce.inventory.ReservationReleased"] * 2
    assert svc.level("SKU-1001").reserved == 0


def test_restock_is_idempotent_on_restock_id(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    body = {"orderId": ORDER, "returnId": "ret-1", "restockId": "rs-1", "lines": [{"sku": "SKU-1001", "quantity": 1}]}
    svc.h.deliver(svc.registry, svc.h.command(RestockItems, body, key=ORDER, producer="returns-svc"))
    svc.h.deliver(svc.registry, svc.h.command(RestockItems, body, key=ORDER, producer="returns-svc"))
    assert len([p for p in svc.h.published() if p.type.endswith("ItemsRestocked")]) == 2
    assert svc.level("SKU-1001").on_hand == 11


def test_command_past_envelope_expiry_is_rejected(svc: Svc) -> None:
    svc.set_stock("SKU-1001", 10)
    svc.h.published()
    rec = svc.h.command(
        ReserveStock,
        {"orderId": ORDER, "reservationId": "r-7", "ttlSeconds": 900, "lines": [{"sku": "SKU-1001", "quantity": 1}]},
        key=ORDER,
        expires_at=svc.h.clock.now() - timedelta(seconds=1),
    )
    svc.h.deliver(svc.registry, rec)
    assert [p.type for p in svc.h.published()] == ["com.edacommerce.inventory.StockReservationRejected"]


def test_unknown_type_on_command_topic_is_ignored(svc: Svc) -> None:
    from edacommon.consumer import ConsumedRecord

    rec = ConsumedRecord(
        topic="inventory.commands.v1",
        partition=0,
        offset=1,
        key=b"o",
        value=b"??",
        headers=[("ce_type", b"com.edacommerce.inventory.TransferStock"), ("ce_id", b"x1")],
    )
    assert svc.h.deliver(svc.registry, rec) is Outcome.IGNORED


def test_admin_api_sets_stock_and_publishes_level(svc: Svc) -> None:
    from edacommon.http import Authenticator, Readiness, create_app
    from fastapi.testclient import TestClient
    from inventory_svc.adapters.inbound.http.routes import admin_router

    app = create_app(
        svc.settings,
        readiness=Readiness(),
        instrument=False,
        routers=[admin_router(svc.h.db, svc.inventory_for, svc.h.clock, Authenticator(svc.settings))],
    )
    c = TestClient(app)
    r = c.put("/admin/stock/SKU-1003", json={"onHand": 200})
    assert r.status_code == 200 and r.json()["available"] == 200
    (lvl,) = svc.h.published()
    assert lvl.type.endswith("StockLevelChanged") and lvl.key == "SKU-1003" and lvl.envelope["aggregateVersion"] == 1
    assert c.put("/admin/stock/SKU-1003", json={"onHand": -1}).status_code == 400
    assert c.get("/health/live").json() == {"status": "UP"}
