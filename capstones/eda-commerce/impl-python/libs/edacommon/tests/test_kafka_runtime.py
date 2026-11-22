"""The consumer runtime against a real Kafka broker and a real Postgres (checklist §11, layer 3).

* command in -> handler -> outbox -> polling relay -> reply on the topic, with Debezium-identical
  headers and the murmur2 partition Java would choose;
* RetryLater -> <group>.retry.10s -> the retry consumer waits for x-not-before, then succeeds;
* NonRetryable -> <group>.dlq -> GET /ops/dlq peek -> replay -> processed exactly once;
* crash after DB commit and before offset commit -> redelivered as a duplicate, one effect;
* graceful shutdown finishes the in-flight record and commits its offset.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import contracts_py
import pytest
from confluent_kafka import Consumer, Producer, TopicPartition
from confluent_kafka.schema_registry import Schema
from contracts_py.records import ReserveStock
from contracts_py.topics import retry_topics
from edacommon.config import ServiceSettings
from edacommon.consumer import HandlerRegistry, MessageProcessor
from edacommon.consumer.dlq import DlqOps
from edacommon.consumer.forwarder import Forwarder
from edacommon.consumer.loop import ConsumerLoop
from edacommon.db import Database, UnitOfWork
from edacommon.envelope import MessageContext, OutgoingMessage
from edacommon.errors import NonRetryable, RetryLater
from edacommon.ids import ManualClock, SystemClock
from edacommon.kafka import consumer_config, java_partition, producer_config
from edacommon.outbox import OutboxWriter, PollingRelay
from edacommon.serde import AvroSerde
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import create_topics
from sqlalchemy import text

from .conftest import example

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.slow]
TYPE = "com.edacommerce.inventory.ReserveStock"
REPLY = "com.edacommerce.inventory.ReservationReleased"


class Env:
    def __init__(self, kafka: str, db: Database, registry: Any, metrics: Any, clock: Any) -> None:
        uid = uuid.uuid4().hex[:8]
        self.cmd_topic = f"it-{uid}.commands.v1"
        self.reply_topic = f"it-{uid}.events.v1"
        self.group = f"it-{uid}-svc"
        create_topics(kafka, [self.cmd_topic, self.reply_topic], partitions=12)
        create_topics(kafka, list(retry_topics(self.group)), partitions=6)
        create_topics(kafka, [f"{self.group}.dlq"], partitions=3)
        registry.register_schema(f"{self.cmd_topic}-{TYPE}", Schema(contracts_py.schema_str(TYPE), "AVRO"))
        registry.register_schema(f"{self.reply_topic}-{REPLY}", Schema(contracts_py.schema_str(REPLY), "AVRO"))
        self.settings = ServiceSettings(service_name=self.group, kafka_bootstrap_servers=kafka)
        self.db = db
        self.serde = AvroSerde(registry)
        self.clock = clock
        self.metrics = metrics
        self.producer = Producer(producer_config(self.settings))
        self.writer = OutboxWriter(self.serde, "order-svc", SystemClock())
        self.failures: list[Exception] = []
        self.handled = threading.Event()
        self.in_handler = threading.Event()
        self.handler_delay = 0.0
        self.registry = HandlerRegistry()
        reply_topic = self.reply_topic

        @self.registry.handler(ReserveStock)
        def on_reserve(cmd: ReserveStock, ctx: MessageContext, uow: UnitOfWork) -> None:
            self.in_handler.set()
            if self.handler_delay:
                time.sleep(self.handler_delay)
            if self.failures:
                raise self.failures.pop(0)
            uow.session.execute(
                text("INSERT INTO effect (id, n) VALUES (:id, 1) ON CONFLICT (id) DO UPDATE SET n = effect.n + 1"),
                {"id": cmd.reservation_id},
            )
            OutboxWriter(self.serde, self.group, SystemClock()).append(
                uow.session,
                OutgoingMessage(
                    topic=reply_topic,
                    record_type=REPLY,
                    key=cmd.order_id,
                    aggregate_type="Reservation",
                    aggregate_id=cmd.reservation_id,
                    body={
                        "orderId": cmd.order_id,
                        "reservationId": cmd.reservation_id,
                        "reason": "ok",
                        "releasedAt": SystemClock().now(),
                    },
                ),
            )
            uow.after_commit(self.handled.set)

        self.processor = MessageProcessor(
            group=self.group,
            registry=self.registry,
            db=db,
            serde=self.serde,
            forwarder=Forwarder(self.producer, self.group),
            metrics=metrics,
            clock=clock,
        )

    def send_command(self, order_id: str | None = None) -> str:
        """Write a ReserveStock to an outbox and relay it, exactly as a producing service would."""
        value = example(TYPE)
        order_id = order_id or str(uuid.uuid4())
        value["orderId"] = order_id
        body = {k: v for k, v in value.items() if k != "envelope"}
        with self.db.unit_of_work() as uow:
            appended = self.writer.append(
                uow.session,
                OutgoingMessage(
                    topic=self.cmd_topic,
                    record_type=TYPE,
                    key=order_id,
                    body=body,
                    aggregate_type="Reservation",
                    aggregate_id=value["reservationId"],
                ),
            )
        PollingRelay(self.db, self.producer, self.metrics).publish_once()
        return appended.event_id

    def loop(self, *, retry: bool = False, cls: type[ConsumerLoop] = ConsumerLoop, group: str | None = None) -> ConsumerLoop:
        g = group or (f"{self.group}-retry" if retry else self.group)
        conf = consumer_config(self.settings, g)
        conf["session.timeout.ms"] = 6000
        topics = list(retry_topics(self.group)) if retry else [self.cmd_topic]
        return cls(consumer_conf=conf, topics=topics, processor=self.processor, clock=self.clock, retry_mode=retry, name=g)

    def effects(self) -> int:
        with self.db.unit_of_work() as uow:
            return int(uow.session.execute(text("SELECT coalesce(sum(n),0) FROM effect")).scalar_one())

    def read(self, topic: str, n: int, timeout: float = 20.0) -> list[Any]:
        c = Consumer(
            {
                "bootstrap.servers": self.settings.kafka_bootstrap_servers,
                "group.id": f"reader-{uuid.uuid4().hex}",
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
            }
        )
        c.subscribe([topic])
        out: list[Any] = []
        deadline = time.monotonic() + timeout
        while len(out) < n and time.monotonic() < deadline:
            m = c.poll(0.5)
            if m is not None and not m.error():
                out.append(m)
        c.close()
        return out


def run_in_thread(loop: ConsumerLoop) -> threading.Thread:
    t = threading.Thread(target=loop.run, daemon=True)
    t.start()
    return t


def wait_for(pred: Any, timeout: float = 25.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.1)
    raise AssertionError("condition not met in time")


@pytest.fixture
def env(kafka: str, db: Database, schema_registry: Any, metrics_reader: Any) -> Env:
    return Env(kafka, db, schema_registry, metrics_reader[0], ManualClock(SystemClock().now()))


def test_command_in_reply_out_with_debezium_headers_and_murmur2(env: Env) -> None:
    order_id = "6ed9d0ed-127a-524b-b079-a06e34f3ec73"
    event_id = env.send_command(order_id)
    (cmd,) = env.read(env.cmd_topic, 1)
    assert cmd.partition() == java_partition(order_id, 12), "polling relay must partition like Java (murmur2)"
    names = [k for k, _ in cmd.headers()]
    assert names == [
        "id",
        "ce_id",
        "ce_type",
        "ce_source",
        "ce_time",
        "correlation_id",
        "causation_id",
        "traceparent",
        "tracestate",
        "ce_specversion",
    ]
    loop = env.loop()
    t = run_in_thread(loop)
    wait_for(env.handled.is_set)
    PollingRelay(env.db, env.producer, env.metrics).publish_once()
    (reply,) = env.read(env.reply_topic, 1)
    h = {k: (v.decode() if v else None) for k, v in reply.headers()}
    assert h["causation_id"] == event_id and h["ce_type"] == REPLY and reply.key() == order_id.encode()
    assert reply.partition() == java_partition(order_id, 12)
    loop.stop()
    t.join(10)
    assert env.effects() == 1


def test_retry_later_goes_through_retry_topic_and_succeeds(env: Env, metrics_reader: Any) -> None:
    env.failures = [RetryLater("dependency degraded")]
    env.send_command()
    main, retry = env.loop(), env.loop(retry=True)
    threads = [run_in_thread(main), run_in_thread(retry)]
    (fwd,) = env.read(f"{env.group}.retry.10s", 1)
    h = {k: (v.decode() if v else None) for k, v in fwd.headers()}
    assert h["x-retry-attempt"] == "1" and h["x-original-topic"] == env.cmd_topic
    (orig,) = env.read(env.cmd_topic, 1)
    assert fwd.value() == orig.value() and fwd.key() == orig.key()
    time.sleep(2.0)
    assert env.effects() == 0, "must wait for x-not-before"
    env.clock.advance(11)
    wait_for(lambda: env.effects() == 1)
    for lp in (main, retry):
        lp.stop()
    for t in threads:
        t.join(10)
    reader = metrics_reader[1]
    assert counter_value(reader, "eda.consumer.processed", outcome="retry") == 1
    assert counter_value(reader, "eda.consumer.processed", outcome="success") == 1


def test_dlq_peek_and_replay_processes_once(env: Env) -> None:
    env.failures = [NonRetryable("unknown reservation")]
    event_id = env.send_command()
    main, retry = env.loop(), env.loop(retry=True)
    threads = [run_in_thread(main), run_in_thread(retry)]
    env.read(f"{env.group}.dlq", 1)
    ops = DlqOps(consumer_conf=consumer_config(env.settings, "x"), producer=env.producer, group=env.group, clock=env.clock)
    (entry,) = ops.peek(10)
    assert entry.eventId == event_id and entry.eventType == TYPE and entry.errorClass == "NonRetryable"
    assert entry.originalTopic == env.cmd_topic and entry.errorMessage == "unknown reservation"
    assert ops.replay(max_messages=10) == 1
    wait_for(lambda: env.effects() == 1)
    assert ops.peek(10) == [], "replayed entries are no longer pending"
    assert ops.replay(max_messages=10) == 0
    time.sleep(1)
    assert env.effects() == 1
    for lp in (main, retry):
        lp.stop()
    for t in threads:
        t.join(10)


class CrashingLoop(ConsumerLoop):
    """Simulates a crash between the DB commit and the offset commit."""

    def _commit(self, *, sync: bool, only: Any = None) -> None:
        return None


def test_crash_after_db_commit_before_offset_commit_is_a_duplicate(env: Env, metrics_reader: Any) -> None:
    env.send_command()
    crashing = env.loop(cls=CrashingLoop)
    t = run_in_thread(crashing)
    wait_for(env.handled.is_set)
    crashing.stop()
    t.join(15)
    assert env.effects() == 1
    restarted = env.loop()
    t2 = run_in_thread(restarted)
    wait_for(lambda: counter_value(metrics_reader[1], "eda.consumer.processed", outcome="duplicate") == 1)
    restarted.stop()
    t2.join(15)
    assert env.effects() == 1, "redelivery after a crash must not repeat the effect"


def test_graceful_shutdown_finishes_record_and_commits(env: Env) -> None:
    env.handler_delay = 2.0
    env.send_command()
    loop = env.loop()
    t = run_in_thread(loop)
    wait_for(env.in_handler.is_set)
    started = time.monotonic()
    loop.stop()  # what SIGTERM does
    t.join(20)
    assert not t.is_alive() and time.monotonic() - started < 10
    assert env.effects() == 1, "in-flight record finished"
    c = Consumer({**consumer_config(env.settings, env.group)})
    committed = c.committed([TopicPartition(env.cmd_topic, p) for p in range(12)], timeout=10)
    c.close()
    assert sum(1 for tp in committed if tp.offset == 1) == 1, "its offset was committed on shutdown"
