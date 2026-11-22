"""Build and read the Avro ``Envelope``; derive Kafka headers (guide §4 ``envelope``, architecture §8.3).

Rules that must match the Java build:

* ``type`` = Avro full name; ``partitionKey`` = record key; ``causationId`` = the triggering
  ``eventId``; ``correlationId`` inherited from the trigger; ``occurredAt`` from the clock.
* ``version`` = the ``.vN`` suffix of the topic.
* Headers are exactly the ones Debezium's outbox router produces from the outbox columns, so the
  polling relay and Debezium are indistinguishable to consumers.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

HEADER_ID = "id"
CE_ID = "ce_id"
CE_TYPE = "ce_type"
CE_SOURCE = "ce_source"
CE_SPECVERSION = "ce_specversion"
CE_TIME = "ce_time"
CORRELATION_ID = "correlation_id"
CAUSATION_ID = "causation_id"
TRACEPARENT = "traceparent"
TRACESTATE = "tracestate"

Headers = Sequence[tuple[str, bytes | None]]


def truncate_ms(dt: datetime) -> datetime:
    """Avro timestamp-millis keeps milliseconds; keep the DB copy identical."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime")
    return dt.astimezone(UTC).replace(microsecond=(dt.microsecond // 1000) * 1000)


def debezium_time(dt: datetime) -> str:
    """Render a timestamptz the way Debezium's ZonedTimestamp does (ISO_OFFSET_DATE_TIME, UTC as Z).

    Java prints the fraction only when non-zero, in groups of 3 digits. The polling relay uses this
    so its ``ce_time`` header is byte-identical to Debezium's.
    """
    dt = dt.astimezone(UTC)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    us = dt.microsecond
    if us == 0:
        return base + "Z"
    if us % 1000 == 0:
        return f"{base}.{us // 1000:03d}Z"
    return f"{base}.{us:06d}Z"


def topic_major_version(topic: str) -> int:
    try:
        return int(topic.rsplit(".v", 1)[1])
    except (IndexError, ValueError):
        return 1


@dataclass(frozen=True, slots=True)
class Causation:
    """What caused the message being written: the flow id and the triggering event id."""

    correlation_id: str
    causation_id: str | None = None


_current_causation: contextvars.ContextVar[Causation | None] = contextvars.ContextVar(
    "eda_causation", default=None
)


def current_causation() -> Causation | None:
    return _current_causation.get()


@contextmanager
def caused_by(causation: Causation) -> Iterator[None]:
    token = _current_causation.set(causation)
    try:
        yield
    finally:
        _current_causation.reset(token)


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A message to append to the outbox. ``body`` holds every field except ``envelope`` (Avro shape)."""

    topic: str
    record_type: str
    key: str
    body: Mapping[str, Any]
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int = 0
    expires_at: datetime | None = None
    causation: Causation | None = None  # overrides the ambient causation (e.g. timers, HTTP)


def build_envelope(
    *,
    event_id: str,
    record_type: str,
    topic: str,
    producer: str,
    key: str,
    aggregate_type: str,
    aggregate_id: str,
    aggregate_version: int,
    correlation_id: str,
    causation_id: str | None,
    occurred_at: datetime,
    traceparent: str | None,
    tracestate: str | None,
    expires_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "eventId": event_id,
        "type": record_type,
        "version": topic_major_version(topic),
        "occurredAt": truncate_ms(occurred_at),
        "correlationId": correlation_id,
        "causationId": causation_id,
        "traceparent": traceparent,
        "tracestate": tracestate,
        "producer": producer,
        "partitionKey": key,
        "aggregateType": aggregate_type,
        "aggregateId": aggregate_id,
        "aggregateVersion": aggregate_version,
        "tenantId": None,
        "expiresAt": truncate_ms(expires_at) if expires_at else None,
    }


@dataclass(frozen=True, slots=True)
class OutboxRow:
    """One outbox row (columns of contracts/sql/common-tables.sql)."""

    id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    topic: str
    payload: bytes
    occurred_at: datetime
    producer: str
    correlation_id: str
    causation_id: str | None
    traceparent: str | None
    tracestate: str | None


def headers_for_row(row: OutboxRow) -> list[tuple[str, bytes | None]]:
    """Kafka headers exactly as the Debezium connectors in infra/connect/connectors produce them.

    EventRouter adds ``id``; ``table.fields.additional.placement`` maps the columns in this order; the
    InsertHeader SMT appends ``ce_specversion``. Null columns become null-valued headers there too.
    """

    def enc(v: str | None) -> bytes | None:
        return None if v is None else v.encode("utf-8")

    return [
        (HEADER_ID, enc(row.id)),
        (CE_ID, enc(row.id)),
        (CE_TYPE, enc(row.event_type)),
        (CE_SOURCE, enc(row.producer)),
        (CE_TIME, enc(debezium_time(row.occurred_at))),
        (CORRELATION_ID, enc(row.correlation_id)),
        (CAUSATION_ID, enc(row.causation_id)),
        (TRACEPARENT, enc(row.traceparent)),
        (TRACESTATE, enc(row.tracestate)),
        (CE_SPECVERSION, b"1.0"),
    ]


def headers_to_dict(headers: Headers | None) -> dict[str, str | None]:
    """Decode Kafka headers to text. The last value wins for repeated names."""
    out: dict[str, str | None] = {}
    for name, value in headers or ():
        out[name] = None if value is None else value.decode("utf-8", errors="replace")
    return out


@dataclass(frozen=True, slots=True)
class MessageContext:
    """Everything a handler may know about the record it is handling, besides the body."""

    topic: str
    partition: int
    offset: int
    key: str | None
    event_id: str
    event_type: str
    consumer_group: str
    headers: Mapping[str, str | None] = field(default_factory=dict)
    envelope: Mapping[str, Any] = field(default_factory=dict)
    attempt: int = 0  # 0 on the main topic, n on <group>.retry.* (x-retry-attempt)

    @property
    def correlation_id(self) -> str:
        return str(self.envelope.get("correlationId") or self.headers.get(CORRELATION_ID) or self.key or "")

    @property
    def occurred_at(self) -> datetime | None:
        v = self.envelope.get("occurredAt")
        return v if isinstance(v, datetime) else None

    @property
    def expires_at(self) -> datetime | None:
        v = self.envelope.get("expiresAt")
        return v if isinstance(v, datetime) else None

    def causation(self) -> Causation:
        return Causation(correlation_id=self.correlation_id, causation_id=self.event_id)

    def is_expired(self, now: datetime) -> bool:
        """Commands only: a command received after envelope.expiresAt must be rejected, not acted on."""
        exp = self.expires_at
        return exp is not None and now > exp
