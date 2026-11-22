"""A per-service integration harness: real Postgres (migrated with the service's own Alembic
scripts), the real consumer processor and polling relay, a fake broker and an in-memory registry.

Typical service test::

    h = ServiceHarness(url=pg_url, migrations=MIGRATIONS, group="inventory-svc", ...)
    rec = h.command(ReserveStock, {...}, key=order_id)
    assert h.deliver(registry, rec) is Outcome.SUCCESS
    (reply,) = h.published()
    assert reply.type == "com.edacommerce.inventory.StockReserved"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from edacommon.config import ServiceSettings
from edacommon.consumer import ConsumedRecord, HandlerRegistry, MessageProcessor, Outcome
from edacommon.consumer.forwarder import Forwarder
from edacommon.db import Database, make_engine
from edacommon.envelope import build_envelope
from edacommon.ids import Clock, new_id
from edacommon.metrics import EdaMetrics
from edacommon.outbox import OutboxWriter, PollingRelay
from edacommon.serde import AvroSerde, validate
from edacommon.testing.fakes import FakeProducer
from edacommon.testing.infra import migrate

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


@dataclass(frozen=True)
class Published:
    topic: str
    key: str | None
    type: str
    value: dict[str, Any]
    headers: dict[str, str | None]

    @property
    def envelope(self) -> dict[str, Any]:
        env: dict[str, Any] = self.value["envelope"]
        return env


class ServiceHarness:
    def __init__(
        self,
        *,
        url: str,
        migrations: Path,
        group: str,
        serde: AvroSerde,
        clock: Clock,
        metrics: EdaMetrics,
        producer: FakeProducer | None = None,
        pool_size: int = 8,
    ) -> None:
        migrate(url, migrations)
        self.url = url
        self.group = group
        self.serde = serde
        self.clock = clock
        self.metrics = metrics
        self.producer = producer or FakeProducer()
        self.db = Database(make_engine(ServiceSettings(db_pool_size=pool_size, service_name=group), url=url))
        self.outbox = OutboxWriter(serde, group, clock)
        self._seen = 0
        self._offset = 0

    def close(self) -> None:
        self.db.dispose()

    def processor(self, registry: HandlerRegistry) -> MessageProcessor:
        return MessageProcessor(
            group=self.group,
            registry=registry,
            db=self.db,
            serde=self.serde,
            forwarder=Forwarder(self.producer, self.group),
            metrics=self.metrics,
            clock=self.clock,
            sleep=lambda s: None,
        )

    def command(
        self,
        record_cls: type[Any],
        body: dict[str, Any],
        *,
        key: str,
        event_id: str | None = None,
        correlation_id: str | None = None,
        producer: str = "order-svc",
        occurred_at: datetime | None = None,
        expires_at: datetime | None = None,
        aggregate_version: int = 0,
    ) -> ConsumedRecord:
        """Build a record exactly as another service's outbox + Debezium would deliver it."""
        event_id = event_id or new_id()
        topic = record_cls.TOPIC
        env = build_envelope(
            event_id=event_id,
            record_type=record_cls.AVRO_NAME,
            topic=topic,
            producer=producer,
            key=key,
            aggregate_type=record_cls.AGGREGATE_TYPE,
            aggregate_id=key,
            aggregate_version=aggregate_version,
            correlation_id=correlation_id or key,
            causation_id=None,
            occurred_at=occurred_at or self.clock.now(),
            traceparent=TRACEPARENT,
            tracestate=None,
            expires_at=expires_at,
        )
        value = {"envelope": env, **body}
        validate(record_cls.AVRO_NAME, value)
        data = self.serde.serialize(topic, record_cls.AVRO_NAME, value)
        self._offset += 1
        headers = [
            ("id", event_id.encode()),
            ("ce_id", event_id.encode()),
            ("ce_type", record_cls.AVRO_NAME.encode()),
            ("ce_source", producer.encode()),
            ("correlation_id", (correlation_id or key).encode()),
            ("traceparent", TRACEPARENT.encode()),
            ("ce_specversion", b"1.0"),
        ]
        return ConsumedRecord(topic=topic, partition=0, offset=self._offset, key=key.encode(), value=data, headers=headers)

    def deliver(self, registry: HandlerRegistry, record: ConsumedRecord) -> Outcome:
        return self.processor(registry).process(record).outcome

    def published(self) -> list[Published]:
        """Run the polling relay and return (decoded) records published since the last call."""
        PollingRelay(self.db, self.producer, self.metrics).publish_once()
        new = self.producer.records[self._seen :]
        self._seen = len(self.producer.records)
        out = []
        for r in new:
            hm = r.header_map
            etype = hm.get("ce_type")
            if etype is None or r.value is None or ".retry." in r.topic or r.topic.endswith(".dlq"):
                continue
            value = self.serde.deserialize(r.topic, etype, r.value)
            out.append(Published(r.topic, r.key.decode() if r.key else None, etype, value, hm))
        return out
