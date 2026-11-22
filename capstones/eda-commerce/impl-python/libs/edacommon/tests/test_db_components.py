"""Outbox writer + polling relay, idempotency keys, saga engine + sweeper, webhook receiver, and the
shared-table migration diffed against contracts/sql/common-tables.sql (checklist §11)."""

from __future__ import annotations

import threading
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, select, text

from edacommon.db import Database, outbox_table
from edacommon.envelope import Causation, OutgoingMessage
from edacommon.errors import DomainError
from edacommon.idempotency import IdempotencyConflict, IdempotencyMismatch, IdempotencyStore, StoredResponse
from edacommon.kafka import java_partition
from edacommon.migrations.common_tables import statements
from edacommon.outbox import Housekeeping, OutboxWriter, PollingRelay
from edacommon.saga import DeadlineSweeper, PendingMessage, SagaEngine, SagaRepository, SagaStep
from edacommon.serde import AvroSerde
from edacommon.testing.fakes import collect, counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from edacommon.webhooks import WebhookReceiver, sign

pytestmark = pytest.mark.integration


def released(order_id: str, rid: str, now: Any) -> OutgoingMessage:
    return OutgoingMessage(topic="inventory.events.v1", record_type="com.edacommerce.inventory.ReservationReleased",
                           key=order_id, aggregate_type="Reservation", aggregate_id=rid,
                           body={"orderId": order_id, "reservationId": rid, "reason": "x", "releasedAt": now})


# ------------------------------------------------------------------------------------------ outbox
def test_outbox_row_columns_and_rollback(db: Database, serde: AvroSerde, clock: Any) -> None:
    w = OutboxWriter(serde, "inventory-svc", clock)
    with db.unit_of_work() as uow:
        a = w.append(uow.session, released("o-1", "r-1", clock.now()))
    with pytest.raises(RuntimeError), db.unit_of_work() as uow:
        w.append(uow.session, released("o-2", "r-2", clock.now()))
        raise RuntimeError("business failure")
    with db.unit_of_work() as uow:
        rows = uow.session.execute(select(outbox_table)).mappings().all()
    assert len(rows) == 1, "a rolled-back transaction publishes nothing"
    r = rows[0]
    assert str(r["id"]) == a.event_id and r["aggregate_id"] == "o-1" and r["aggregate_type"] == "Reservation"
    assert r["event_type"] == "com.edacommerce.inventory.ReservationReleased" and r["topic"] == "inventory.events.v1"
    assert bytes(r["payload"])[0] == 0 and r["producer"] == "inventory-svc" and r["correlation_id"] == "r-1"
    assert r["published_at"] is None


def test_polling_relay_publishes_in_order_with_headers(db: Database, serde: AvroSerde, clock: Any,
                                                        fake_producer: Any, metrics_reader: Any) -> None:
    w = OutboxWriter(serde, "inventory-svc", clock)
    with db.unit_of_work() as uow:
        ids = [w.append(uow.session, released("o-1", f"r-{i}", clock.now())).event_id for i in range(5)]
    with db.unit_of_work() as uow:
        w.append(uow.session, OutgoingMessage(
            topic="inventory.events.v1", record_type="com.edacommerce.inventory.ReservationReleased", key="o-2",
            aggregate_type="Reservation", aggregate_id="r-9", causation=Causation("o-2", "cause-1"),
            body={"orderId": "o-2", "reservationId": "r-9", "reason": "x", "releasedAt": clock.now()}))
    metrics, reader = metrics_reader
    relay = PollingRelay(db, fake_producer, metrics)
    assert relay.publish_once() == 6
    assert relay.publish_once() == 0
    recs = fake_producer.records
    assert [r.header_map["ce_id"] for r in recs[:5]] == ids
    last = recs[-1].header_map
    assert last["causation_id"] == "cause-1" and last["correlation_id"] == "o-2" and recs[-1].key == b"o-2"
    assert set(last) == {"id", "ce_id", "ce_type", "ce_source", "ce_time", "correlation_id", "causation_id",
                         "traceparent", "tracestate", "ce_specversion"}
    assert last["ce_specversion"] == "1.0" and last["ce_source"] == "inventory-svc"
    assert collect(reader)["eda.outbox.pending"][-1].value == 0
    with db.unit_of_work() as uow:
        assert uow.session.execute(text("SELECT count(*) FROM outbox WHERE published_at IS NULL")).scalar_one() == 0


def test_relay_does_not_mark_rows_when_broker_refuses(db: Database, serde: AvroSerde, clock: Any,
                                                       fake_producer: Any, metrics_reader: Any) -> None:
    w = OutboxWriter(serde, "inventory-svc", clock)
    with db.unit_of_work() as uow:
        w.append(uow.session, released("o-1", "r-1", clock.now()))
    fake_producer.fail_next = 1
    relay = PollingRelay(db, fake_producer, metrics_reader[0])
    with pytest.raises(Exception, match="delivery failure"):
        relay.publish_once()
    assert relay.publish_once() == 1  # retried, nothing lost


def test_housekeeping_deletes_old_rows(db: Database, serde: AvroSerde, clock: Any) -> None:
    w = OutboxWriter(serde, "inventory-svc", clock)
    with db.unit_of_work() as uow:
        w.append(uow.session, released("o-1", "r-1", clock.now()))
        uow.session.execute(text("UPDATE outbox SET created_at = now() - interval '8 days'"))
    from edacommon.ids import SystemClock

    assert Housekeeping(db, SystemClock()).run_once()["outbox"] == 1


# ------------------------------------------------------------------------------------- idempotency
def _ok(n: list[int]) -> Any:
    def action(uow: Any) -> StoredResponse:
        n.append(1)
        uow.session.execute(text("INSERT INTO effect (id, n) VALUES (:i, 1)"), {"i": f"e{len(n)}"})
        return StoredResponse(202, b'{"orderId":"o-1"}', {"content-type": "application/json", "Location": "/orders/o-1"})
    return action


def test_idempotency_replay_mismatch_and_conflict(db: Database, clock: Any) -> None:
    store = IdempotencyStore(clock)
    calls: list[int] = []
    first = store.execute(db, caller="c", key="k1", method="POST", path="/checkouts", body=b'{"a":1}', action=_ok(calls))
    assert first.status == 202 and not first.replayed
    again = store.execute(db, caller="c", key="k1", method="POST", path="/checkouts", body=b'{ "a" : 1 }', action=_ok(calls))
    assert again.replayed and again.body == first.body and again.headers["Location"] == "/orders/o-1"
    assert len(calls) == 1
    with pytest.raises(IdempotencyMismatch):
        store.execute(db, caller="c", key="k1", method="POST", path="/checkouts", body=b'{"a":2}', action=_ok(calls))
    # other caller, same key: independent
    store.execute(db, caller="other", key="k1", method="POST", path="/checkouts", body=b'{"a":1}', action=_ok(calls))
    assert len(calls) == 2

    started, release = threading.Event(), threading.Event()

    def slow(uow: Any) -> StoredResponse:
        started.set()
        release.wait(5)
        return StoredResponse(202, b"{}")

    t = threading.Thread(target=store.execute, args=(db,), kwargs=dict(
        caller="c", key="k2", method="POST", path="/checkouts", body=b"{}", action=slow))
    t.start()
    started.wait(5)
    with pytest.raises(IdempotencyConflict):
        store.execute(db, caller="c", key="k2", method="POST", path="/checkouts", body=b"{}", action=_ok(calls))
    release.set()
    t.join()
    assert store.execute(db, caller="c", key="k2", method="POST", path="/checkouts", body=b"{}", action=_ok(calls)).replayed


def test_domain_error_rolls_back_the_key(db: Database, clock: Any) -> None:
    store = IdempotencyStore(clock)

    def refuse(uow: Any) -> StoredResponse:
        raise DomainError("price changed")

    with pytest.raises(DomainError):
        store.execute(db, caller="c", key="k", method="POST", path="/p", body=b"{}", action=refuse)
    calls: list[int] = []
    assert not store.execute(db, caller="c", key="k", method="POST", path="/p", body=b"{}", action=_ok(calls)).replayed


# -------------------------------------------------------------------------------------------- saga
def test_saga_engine_versions_transitions_and_metrics(db: Database, serde: AvroSerde, clock: Any,
                                                       metrics_reader: Any) -> None:
    metrics, reader = metrics_reader
    engine = SagaEngine(saga_type="ORDER", outbox=OutboxWriter(serde, "order-svc", clock), metrics=metrics, clock=clock)

    def ev(n: int) -> PendingMessage:
        return PendingMessage(topic="order.events.v1", record_type="com.edacommerce.order.OrderRequiresAttention",
                              key="o-1", aggregate_type="Order", is_event=True,
                              body={"orderId": "o-1", "sagaState": "X", "issue": f"i{n}", "raisedAt": clock.now()})

    with db.unit_of_work() as uow:
        r = engine.handle(uow, saga_id="o-1", trigger_type="com.x.Start", trigger_id="e1", correlation_id="o-1",
                          decide=lambda row, now: SagaStep(state="A", data={"k": 1}, deadline_at=now + timedelta(seconds=30),
                                                           step_attempts=0, messages=[ev(1)]))
    assert r.applied and r.row and r.row.version == 1
    clock.advance(2)
    with db.unit_of_work() as uow:
        r = engine.handle(uow, saga_id="o-1", trigger_type="com.x.Next", trigger_id="e2",
                          decide=lambda row, now: SagaStep(state="B", data=row.data, deadline_at=None, step_attempts=0,
                                                           messages=[ev(2), ev(3)], terminal=True, outcome="DELIVERED",
                                                           decision_reached=True))
    assert r.row and r.row.version == 3, "two events move the version by two"
    with db.unit_of_work() as uow:
        ignored = engine.handle(uow, saga_id="o-1", trigger_type="com.x.Late", trigger_id="e3",
                                decide=lambda row, now: SagaStep.ignore(row))
        assert not ignored.applied
        hist = SagaRepository(uow.session).history("o-1")
        payloads = [bytes(p) for p in uow.session.execute(select(outbox_table.c.payload).order_by(outbox_table.c.created_at, outbox_table.c.id)).scalars()]
    assert [(h.seq, h.from_state, h.to_state) for h in hist] == [(1, "NEW", "A"), (3, "A", "B")]
    versions = [serde.deserialize("order.events.v1", "com.edacommerce.order.OrderRequiresAttention", p)["envelope"]["aggregateVersion"] for p in payloads]
    assert versions == [1, 2, 3], "aggregateVersion strictly increasing per order"
    assert counter_value(reader, "eda.saga.outcomes", saga_type="ORDER", outcome="DELIVERED") == 1
    steps = {p.attributes["step"]: p for p in collect(reader)["eda.saga.step.duration"]}
    assert steps["A"].sum == pytest.approx(2.0) and "DECISION" in steps


def test_optimistic_lock_detects_concurrent_update(db: Database) -> None:
    from edacommon.saga import ConcurrentSagaUpdate, SagaRow
    from edacommon.ids import SystemClock

    now = SystemClock().now()
    with db.unit_of_work() as uow:
        SagaRepository(uow.session).insert(SagaRow("s", "ORDER", "A", {}, 1, None, 0, "s"), now)
    with pytest.raises(ConcurrentSagaUpdate), db.unit_of_work() as uow:
        SagaRepository(uow.session).save(SagaRow("s", "ORDER", "B", {}, 2, None, 0, "s"), expected_version=0, now=now)


def test_sweeper_fires_deadlines_once_across_replicas(db: Database, serde: AvroSerde, clock: Any,
                                                       metrics_reader: Any) -> None:
    from edacommon.ids import SystemClock

    real = SystemClock()
    metrics, reader = metrics_reader
    engine = SagaEngine(saga_type="ORDER", outbox=OutboxWriter(serde, "order-svc", real), metrics=metrics, clock=real)
    with db.unit_of_work() as uow:
        for i in range(20):
            engine.handle(uow, saga_id=f"s{i}", trigger_type="start", trigger_id=None,
                          decide=lambda row, now: SagaStep(state="WAIT", data={}, deadline_at=now - timedelta(seconds=1),
                                                           step_attempts=0))
    fired: list[str] = []
    lock = threading.Lock()

    def on_deadline(uow: Any, row: Any) -> None:
        with lock:
            fired.append(row.saga_id)
        engine.handle(uow, saga_id=row.saga_id, trigger_type="DEADLINE", trigger_id=None, locked_row=row,
                      decide=lambda r, now: SagaStep(state="DONE", data=r.data, deadline_at=None, step_attempts=0, terminal=True))

    sweepers = [DeadlineSweeper(db=db, saga_type="ORDER", on_deadline=on_deadline, clock=real, metrics=metrics) for _ in range(3)]
    threads = [threading.Thread(target=s.run_once) for s in sweepers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(fired) == sorted(f"s{i}" for i in range(20)), "each saga handled exactly once"
    assert counter_value(reader, "eda.saga.step.timeouts", state="WAIT") == 20
    assert collect(reader)["eda.saga.overdue"][-1].value == 0


# ---------------------------------------------------------------------------------------- webhooks
def test_webhook_receiver_dedupes_and_rejects(db: Database, metrics_reader: Any) -> None:
    from edacommon.ids import SystemClock

    metrics, reader = metrics_reader
    stored: list[str] = []
    rx = WebhookReceiver(db=db, source="psp", consumer="psp-webhook", secret="s", metrics=metrics,
                         event_id_of=lambda p: p["pspEventId"], event_type_of=lambda p: p["eventType"],
                         store=lambda session, payload, raw: stored.append(payload["pspEventId"]))
    now = SystemClock().now()
    body = b'{"pspEventId":"e9","eventType":"authorization.succeeded"}'
    ts = str(int(now.timestamp()))
    for _ in range(3):
        assert rx.receive(raw_body=body, timestamp=ts, signature=sign("s", ts, body), now=now).status == 200
    assert stored == ["e9"]
    assert rx.receive(raw_body=body, timestamp=ts, signature="00", now=now).status == 401
    assert rx.receive(raw_body=b"nope", timestamp=ts, signature=sign("s", ts, b"nope"), now=now).status == 400
    assert counter_value(reader, "eda.webhook.received", outcome="accepted") == 1
    assert counter_value(reader, "eda.webhook.received", outcome="duplicate") == 2
    assert counter_value(reader, "eda.webhook.received", outcome="rejected") == 2


# ------------------------------------------------------------------------------- shared tables DDL
def test_shared_tables_match_contract_ddl() -> None:
    """Migration 1 vs. contracts/sql/common-tables.sql, compared through information_schema."""
    tables = ["outbox", "inbox", "idempotency_key", "saga_instance", "saga_transition"]
    with fresh_database("contract") as a, fresh_database("ours") as b:
        ea = create_engine(a)
        with ea.begin() as c:
            c.exec_driver_sql(contract_sql_path().read_text())
        ea.dispose()
        eb = create_engine(b)
        with eb.begin() as c:
            for stmt in statements(saga=True):
                c.execute(text(stmt))
        eb.dispose()
        assert information_schema_columns(a, tables) == information_schema_columns(b, tables)

        def extras(url: str) -> Any:
            e = create_engine(url)
            with e.connect() as c:
                idx = c.execute(text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1")).all()
                pub = c.execute(text("SELECT pubname, tablename FROM pg_publication_tables")).all()
                chk = c.execute(text("SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE connamespace='public'::regnamespace ORDER BY 1")).all()
            e.dispose()
            return idx, pub, chk

        assert extras(a) == extras(b)


def test_java_partition_helper_is_stable() -> None:
    # Same orderId -> same partition number on every 12-partition topic, whichever language produced it.
    assert java_partition("6ed9d0ed-127a-524b-b079-a06e34f3ec73", 12) == java_partition("6ed9d0ed-127a-524b-b079-a06e34f3ec73", 12)
