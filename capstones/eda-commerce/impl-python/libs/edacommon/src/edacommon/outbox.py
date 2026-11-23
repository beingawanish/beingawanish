"""Transactional outbox (ADR-0003): the writer, the polling relay fallback, housekeeping.

``OutboxWriter.append`` serialises the record to Confluent wire format **inside** the business
transaction and inserts one row. Debezium (default) or :class:`PollingRelay` publishes it later.

Envelope derivation (guide §4 ``envelope``): ``eventId`` = row id (UUIDv7), ``causationId`` and
``correlationId`` from the ambient :class:`~edacommon.envelope.Causation` (set by the consumer
runtime for the record being handled, or explicitly by HTTP use cases and timers), trace context
from the active span.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import Session

from edacommon.db import Database, idempotency_table, inbox_table, outbox_table
from edacommon.envelope import (
    Causation,
    OutboxRow,
    OutgoingMessage,
    build_envelope,
    current_causation,
    headers_for_row,
    truncate_ms,
)
from edacommon.ids import Clock, new_id
from edacommon.kafka import encode_key
from edacommon.logging import get_logger
from edacommon.metrics import EdaMetrics
from edacommon.serde import AvroSerde
from edacommon.tracing import current_trace_headers

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AppendedMessage:
    event_id: str
    envelope: dict[str, Any]
    payload: bytes


class OutboxWriter:
    """Appends messages to the outbox in the caller's transaction. Thread-safe and stateless."""

    def __init__(self, serde: AvroSerde, producer: str, clock: Clock) -> None:
        self._serde = serde
        self._producer = producer
        self._clock = clock

    def append(self, session: Session, msg: OutgoingMessage) -> AppendedMessage:
        causation = msg.causation or current_causation()
        if causation is None:
            # A message with no trigger starts a flow: its correlation is its aggregate.
            causation = Causation(correlation_id=msg.aggregate_id, causation_id=None)
        event_id = new_id()
        occurred_at = truncate_ms(self._clock.now())
        traceparent, tracestate = current_trace_headers()
        envelope = build_envelope(
            event_id=event_id,
            record_type=msg.record_type,
            topic=msg.topic,
            producer=self._producer,
            key=msg.key,
            aggregate_type=msg.aggregate_type,
            aggregate_id=msg.aggregate_id,
            aggregate_version=msg.aggregate_version,
            correlation_id=causation.correlation_id,
            causation_id=causation.causation_id,
            occurred_at=occurred_at,
            traceparent=traceparent,
            tracestate=tracestate,
            expires_at=msg.expires_at,
        )
        value = {"envelope": envelope, **msg.body}
        payload = self._serde.serialize(msg.topic, msg.record_type, value)
        session.execute(
            insert(outbox_table).values(
                id=event_id,
                aggregate_type=msg.aggregate_type,
                aggregate_id=msg.key,
                event_type=msg.record_type,
                topic=msg.topic,
                payload=payload,
                occurred_at=occurred_at,
                producer=self._producer,
                correlation_id=causation.correlation_id,
                causation_id=causation.causation_id,
                traceparent=traceparent,
                tracestate=tracestate,
            )
        )
        return AppendedMessage(event_id=event_id, envelope=envelope, payload=payload)


class Publisher(Protocol):
    """The part of a Kafka producer the relay and forwarders need (lets tests use a fake)."""

    def produce(
        self,
        topic: str,
        value: bytes | None = ...,
        key: bytes | None = ...,
        headers: Any = ...,
        on_delivery: Callable[..., None] | None = ...,
    ) -> None: ...

    def flush(self, timeout: float = ...) -> int: ...

    def poll(self, timeout: float = ...) -> int: ...


class DeliveryFailed(Exception):
    pass


def produce_and_wait(
    producer: Publisher,
    items: list[tuple[str, bytes | None, bytes | None, list[tuple[str, bytes | None]]]],
    timeout: float = 30.0,
) -> None:
    """Produce records (topic, key, value, headers) and block until every one is acknowledged."""
    errors: list[str] = []

    def on_delivery(err: Any, _msg: Any) -> None:
        if err is not None:
            errors.append(str(err))

    for topic, key, value, headers in items:
        producer.produce(topic, value=value, key=key, headers=headers, on_delivery=on_delivery)
        producer.poll(0)
    remaining = producer.flush(timeout)
    if remaining:
        raise DeliveryFailed(f"{remaining} record(s) not acknowledged within {timeout}s")
    if errors:
        raise DeliveryFailed("; ".join(errors[:3]))


class PollingRelay:
    """Fallback relay (``OUTBOX_RELAY=polling``): publish unpublished rows in insertion order.

    ``SELECT ... FOR UPDATE SKIP LOCKED`` lets several replicas run without double-publishing a row
    in the same moment; publication is still at-least-once (a crash after the broker ack and before
    the commit re-publishes), exactly like Debezium, and consumers' inboxes absorb it (ADR-0006).
    Ordering: rows are taken in ``(created_at, id)`` order and published synchronously per batch, so
    per-key order is preserved within one relay. With several replicas, per-key order can only be
    guaranteed by running one relay per database, which is the default deployment.
    """

    def __init__(
        self,
        db: Database,
        producer: Publisher,
        metrics: EdaMetrics,
        *,
        interval: timedelta = timedelta(milliseconds=200),
        batch_size: int = 500,
    ) -> None:
        self._db = db
        self._producer = producer
        self._metrics = metrics
        self._interval = interval.total_seconds()
        self._batch = batch_size
        self._wake = threading.Event()
        self._stop = threading.Event()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def publish_once(self) -> int:
        """Publish one batch. Returns the number of rows published."""
        with self._db.unit_of_work() as uow:
            s = uow.session
            rows = (
                s.execute(
                    select(outbox_table)
                    .where(outbox_table.c.published_at.is_(None))
                    .order_by(outbox_table.c.created_at, outbox_table.c.id)
                    .limit(self._batch)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            if rows:
                items: list[tuple[str, bytes | None, bytes | None, list[tuple[str, bytes | None]]]] = []
                for r in rows:
                    row = OutboxRow(
                        id=str(r["id"]),
                        aggregate_type=r["aggregate_type"],
                        aggregate_id=r["aggregate_id"],
                        event_type=r["event_type"],
                        topic=r["topic"],
                        payload=bytes(r["payload"]),
                        occurred_at=r["occurred_at"],
                        producer=r["producer"],
                        correlation_id=r["correlation_id"],
                        causation_id=r["causation_id"],
                        traceparent=r["traceparent"],
                        tracestate=r["tracestate"],
                    )
                    items.append((row.topic, encode_key(row.aggregate_id), row.payload, headers_for_row(row)))
                produce_and_wait(self._producer, items)
                s.execute(
                    update(outbox_table).where(outbox_table.c.id.in_([r["id"] for r in rows])).values(published_at=func.now())
                )
            pending = s.execute(
                select(func.count()).select_from(outbox_table).where(outbox_table.c.published_at.is_(None))
            ).scalar_one()
        self._metrics.outbox_pending(int(pending))
        return len(rows)

    def run(self) -> None:
        log.info("outbox polling relay started")
        while not self._stop.is_set():
            try:
                n = self.publish_once()
            except Exception as exc:
                log.warning("outbox relay batch failed; will retry", error=exc)
                n = 0
                self._stop.wait(1.0)
            if n == 0:
                self._wake.wait(self._interval)
                self._wake.clear()
        log.info("outbox polling relay stopped")


class Housekeeping:
    """Deletes outbox rows after 7 days, inbox rows after 100 days, expired idempotency keys."""

    def __init__(self, db: Database, clock: Clock, *, outbox_days: int = 7, inbox_days: int = 100) -> None:
        self._db = db
        self._clock = clock
        self._outbox = timedelta(days=outbox_days)
        self._inbox = timedelta(days=inbox_days)

    def run_once(self) -> dict[str, int]:
        now: datetime = self._clock.now()
        with self._db.unit_of_work() as uow:
            s = uow.session
            o = s.execute(delete(outbox_table).where(outbox_table.c.created_at < now - self._outbox)).rowcount  # type: ignore[attr-defined]
            i = s.execute(delete(inbox_table).where(inbox_table.c.received_at < now - self._inbox)).rowcount  # type: ignore[attr-defined]
            has_idem = s.execute(text("SELECT to_regclass('idempotency_key') IS NOT NULL")).scalar_one()
            k = 0
            if has_idem:
                k = s.execute(delete(idempotency_table).where(idempotency_table.c.expires_at < now)).rowcount  # type: ignore[attr-defined]
        return {"outbox": o or 0, "inbox": i or 0, "idempotency_key": k or 0}
