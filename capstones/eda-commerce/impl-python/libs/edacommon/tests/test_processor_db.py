"""The consumer algorithm (guide §4.1) against a real Postgres, with a fake broker.

Covers checklist §11: duplicate -> one effect and outcome="duplicate"; unknown ce_type ignored;
Transient retries in place and succeeds; RetryLater lands on <group>.retry.10s with all x-* headers
and raw bytes unchanged; NonRetryable lands on <group>.dlq; retry chain 10s -> 1m -> 10m -> dlq;
trace context parent + the outbox rows written carry the new context; crash after DB commit and
before offset commit replays as a duplicate.
"""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select, text

from contracts_py.records import ReserveStock
from edacommon.consumer import ConsumedRecord, HandlerRegistry, MessageProcessor, Outcome
from edacommon.consumer.forwarder import Forwarder
from edacommon.db import Database, UnitOfWork, outbox_table
from edacommon.envelope import MessageContext, OutgoingMessage
from edacommon.errors import NonRetryable, RetryLater, Transient
from edacommon.outbox import OutboxWriter
from edacommon.serde import AvroSerde
from edacommon.testing.fakes import counter_value

from .conftest import example

pytestmark = pytest.mark.integration

GROUP = "inventory-svc"
TOPIC = "inventory.commands.v1"
TYPE = "com.edacommerce.inventory.ReserveStock"
TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(_exporter))
trace.set_tracer_provider(_provider)


def make_record(serde: AvroSerde, *, event_id: str = "0193a1c4-aaaa-7000-8000-000000000001", offset: int = 7,
                ce_type: str = TYPE, topic: str = TOPIC, extra: list[tuple[str, bytes | None]] | None = None) -> ConsumedRecord:
    value = example(TYPE)
    value["envelope"]["eventId"] = event_id
    data = serde.serialize(TOPIC, TYPE, value)
    headers: list[tuple[str, bytes | None]] = [
        ("id", event_id.encode()), ("ce_id", event_id.encode()), ("ce_type", ce_type.encode()),
        ("ce_source", b"order-svc"), ("correlation_id", value["orderId"].encode()),
        ("traceparent", TRACEPARENT.encode()), ("ce_specversion", b"1.0"),
    ]
    return ConsumedRecord(topic=topic, partition=3, offset=offset, key=value["orderId"].encode(), value=data,
                          headers=headers + (extra or []))


class Harness:
    def __init__(self, db: Database, serde: AvroSerde, producer: Any, metrics: Any, clock: Any) -> None:
        self.db = db
        self.calls = 0
        self.failures: list[Exception] = []
        self.registry = HandlerRegistry()
        self.outbox = OutboxWriter(serde, GROUP, clock)
        self.sleeps: list[float] = []

        @self.registry.handler(ReserveStock)
        def on_reserve(cmd: ReserveStock, ctx: MessageContext, uow: UnitOfWork) -> None:
            self.calls += 1
            if self.failures:
                raise self.failures.pop(0)
            uow.session.execute(text("INSERT INTO effect (id, n) VALUES (:id, 1) "
                                     "ON CONFLICT (id) DO UPDATE SET n = effect.n + 1"), {"id": cmd.reservation_id})
            self.outbox.append(uow.session, OutgoingMessage(
                topic="inventory.events.v1", record_type="com.edacommerce.inventory.ReservationReleased",
                key=cmd.order_id, aggregate_type="Reservation", aggregate_id=cmd.reservation_id,
                body={"orderId": cmd.order_id, "reservationId": cmd.reservation_id, "reason": "test",
                      "releasedAt": clock.now()}))

        self.processor = MessageProcessor(group=GROUP, registry=self.registry, db=db, serde=serde,
                                          forwarder=Forwarder(producer, GROUP), metrics=metrics, clock=clock,
                                          sleep=self.sleeps.append)

    def effects(self) -> int:
        with self.db.unit_of_work() as uow:
            return int(uow.session.execute(text("SELECT coalesce(sum(n), 0) FROM effect")).scalar_one())

    def outbox_rows(self) -> list[Any]:
        with self.db.unit_of_work() as uow:
            return list(uow.session.execute(select(outbox_table)).mappings().all())


@pytest.fixture
def h(db: Database, serde: AvroSerde, fake_producer: Any, metrics_reader: Any, clock: Any) -> Harness:
    metrics, _ = metrics_reader
    return Harness(db, serde, fake_producer, metrics, clock)


def test_success_writes_effect_inbox_and_outbox_with_envelope(h: Harness, serde: AvroSerde, metrics_reader: Any) -> None:
    r = make_record(serde)
    assert h.processor.process(r).outcome is Outcome.SUCCESS
    assert h.effects() == 1
    (row,) = h.outbox_rows()
    assert row["causation_id"] == r.event_id
    assert row["correlation_id"] == r.key_str
    env = serde.deserialize("inventory.events.v1", "com.edacommerce.inventory.ReservationReleased",
                            bytes(row["payload"]))["envelope"]
    assert env["type"] == "com.edacommerce.inventory.ReservationReleased"
    assert env["producer"] == GROUP and env["partitionKey"] == r.key_str and env["causationId"] == r.event_id
    assert env["eventId"] == str(row["id"])
    _, reader = metrics_reader
    assert counter_value(reader, "eda.consumer.processed", outcome="success", event_type=TYPE) == 1


def test_duplicate_has_one_effect_and_is_counted(h: Harness, serde: AvroSerde, metrics_reader: Any) -> None:
    r = make_record(serde)
    assert h.processor.process(r).outcome is Outcome.SUCCESS
    # Crash simulation: the DB committed but the offset did not; the record is delivered again.
    assert h.processor.process(r).outcome is Outcome.DUPLICATE
    assert h.processor.process(make_record(serde, offset=99)).outcome is Outcome.DUPLICATE  # Debezium re-publish
    assert h.effects() == 1 and h.calls == 1 and len(h.outbox_rows()) == 1
    _, reader = metrics_reader
    assert counter_value(reader, "eda.consumer.processed", outcome="duplicate") == 2


def test_unknown_type_is_ignored_without_deserialising(h: Harness, serde: AvroSerde, metrics_reader: Any) -> None:
    r = ConsumedRecord(topic=TOPIC, partition=0, offset=1, key=b"k", value=b"not avro at all",
                       headers=[("ce_type", b"com.edacommerce.inventory.SomethingNew"), ("ce_id", b"x")])
    assert h.processor.process(r).outcome is Outcome.IGNORED
    assert h.calls == 0
    _, reader = metrics_reader
    assert counter_value(reader, "eda.consumer.processed", outcome="ignored") == 1


def test_transient_retries_in_place_then_succeeds(h: Harness, serde: AvroSerde, fake_producer: Any) -> None:
    h.failures = [Transient("deadlock"), Transient("deadlock")]
    assert h.processor.process(make_record(serde)).outcome is Outcome.SUCCESS
    assert h.calls == 3 and h.effects() == 1
    assert len(h.sleeps) == 2 and 0.15 < h.sleeps[0] < 0.25 and 0.3 < h.sleeps[1] < 0.5
    assert fake_producer.records == []


def test_transient_exhausted_goes_to_first_retry_topic(h: Harness, serde: AvroSerde, fake_producer: Any) -> None:
    h.failures = [Transient("db down")] * 5
    assert h.processor.process(make_record(serde)).outcome is Outcome.RETRY
    assert [r.topic for r in fake_producer.records] == [f"{GROUP}.retry.10s"]
    assert h.effects() == 0


def test_retry_later_forwards_raw_bytes_with_x_headers(h: Harness, serde: AvroSerde, fake_producer: Any, clock: Any) -> None:
    r = make_record(serde)
    h.failures = [RetryLater("psp degraded")]
    assert h.processor.process(r).outcome is Outcome.RETRY
    (fwd,) = fake_producer.records
    assert fwd.topic == f"{GROUP}.retry.10s"
    assert fwd.key == r.key and fwd.value == r.value  # unchanged bytes
    hm = fwd.header_map
    assert hm["x-retry-attempt"] == "1"
    assert hm["x-original-topic"] == TOPIC and hm["x-original-partition"] == "3" and hm["x-original-offset"] == "7"
    assert hm["x-error-class"] == "RetryLater" and hm["x-error-message"] == "psp degraded"
    assert hm["x-failed-consumer-group"] == GROUP
    assert hm["x-not-before"] == "2026-11-18T11:06:50.000Z"  # now + 10 s
    assert hm["ce_id"] == r.event_id and hm["ce_type"] == TYPE  # original headers kept
    assert h.effects() == 0


def test_non_retryable_goes_straight_to_dlq(h: Harness, serde: AvroSerde, fake_producer: Any, metrics_reader: Any) -> None:
    h.failures = [NonRetryable("invariant violated")]
    assert h.processor.process(make_record(serde)).outcome is Outcome.DLQ
    assert [r.topic for r in fake_producer.records] == [f"{GROUP}.dlq"]
    _, reader = metrics_reader
    assert counter_value(reader, "eda.dlq.messages", error_class="NonRetryable") == 1


def test_bad_bytes_are_non_retryable(h: Harness, serde: AvroSerde, fake_producer: Any) -> None:
    r = ConsumedRecord(topic=TOPIC, partition=0, offset=1, key=b"k", value=b"\x00\x00\x00\x00\x01garbage",
                       headers=[("ce_type", TYPE.encode()), ("ce_id", b"bad-1")])
    assert h.processor.process(r).outcome is Outcome.DLQ
    assert fake_producer.records[0].topic == f"{GROUP}.dlq"


def test_retry_chain_walks_every_tier_then_dlq(h: Harness, serde: AvroSerde, fake_producer: Any) -> None:
    r = make_record(serde)
    expected = [f"{GROUP}.retry.10s", f"{GROUP}.retry.1m", f"{GROUP}.retry.10m", f"{GROUP}.dlq"]
    for i, topic in enumerate(expected):
        h.failures = [RetryLater(f"attempt {i}")]
        h.processor.process(r)
        fwd = fake_producer.records[-1]
        assert fwd.topic == topic
        assert fwd.value == r.value
        assert fwd.header_map["x-original-topic"] == TOPIC and fwd.header_map["x-original-offset"] == "7"
        r = ConsumedRecord(topic=fwd.topic, partition=0, offset=100 + i, key=fwd.key, value=fwd.value,
                           headers=fwd.headers)
    assert [x.header_map["x-retry-attempt"] for x in fake_producer.records] == ["1", "2", "3", "3"]


def test_retry_topic_record_is_processed_by_same_handler(h: Harness, serde: AvroSerde, fake_producer: Any) -> None:
    h.failures = [RetryLater("later")]
    h.processor.process(make_record(serde))
    fwd = fake_producer.records[0]
    retried = ConsumedRecord(topic=fwd.topic, partition=0, offset=0, key=fwd.key, value=fwd.value, headers=fwd.headers)
    assert h.processor.process(retried).outcome is Outcome.SUCCESS
    assert h.effects() == 1


def test_consumer_span_has_producer_parent_and_outbox_carries_new_context(h: Harness, serde: AvroSerde) -> None:
    _exporter.clear()
    h.processor.process(make_record(serde))
    spans = [s for s in _exporter.get_finished_spans() if s.kind == trace.SpanKind.CONSUMER]
    (span,) = spans
    assert format(span.context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert span.parent is not None and format(span.parent.span_id, "016x") == "00f067aa0ba902b7"
    assert span.links and format(span.links[0].context.span_id, "016x") == "00f067aa0ba902b7"
    assert span.attributes["messaging.system"] == "kafka"
    assert span.attributes["messaging.destination.name"] == TOPIC
    assert span.attributes["messaging.kafka.consumer.group"] == GROUP
    assert span.attributes["messaging.message.id"] == "0193a1c4-aaaa-7000-8000-000000000001"
    (row,) = h.outbox_rows()
    tp = row["traceparent"]
    assert tp.startswith("00-4bf92f3577b34da6a3ce929d0e0e4736-") and tp.split("-")[2] == format(span.context.span_id, "016x")
    assert len(tp) == 55
