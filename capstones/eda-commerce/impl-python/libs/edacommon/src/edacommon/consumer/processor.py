"""The per-record processing algorithm of guide §4.1, independent of the Kafka client.

::

    type = header(r, "ce_type"); handler = registry.get(type)
    if handler is None: outcome "ignored"
    for attempt in 1..5:                                     # in-place retry
        begin tx
            inbox.insert(eventId(r), group) or -> "duplicate"
            msg = deserialize(r.value, handler.reader_schema)
            with consumer_span(r): handler(msg, ctx, uow)      # may append outbox rows
        commit
        "success"
      except Transient:   rollback; sleep(backoff(attempt)); continue
      except RetryLater:  rollback; forward(next retry topic);  "retry"
      except NonRetryable: rollback; forward(dlq);              "dlq"
    else: forward(next retry topic)                           # in-place retries exhausted

The caller (the poll loop) commits the offset only after :meth:`MessageProcessor.process` returns,
i.e. after the DB commit or after the broker acknowledged a forward. Anything that escapes
``process`` (the forward itself failed) means "not done": the loop rewinds and tries again.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from edacommon.consumer.forwarder import Forwarder, current_attempt
from edacommon.consumer.record import ConsumedRecord
from edacommon.consumer.registry import Handler, HandlerRegistry
from edacommon.db import Database
from edacommon.envelope import MessageContext, caused_by
from edacommon.errors import NonRetryable, Transient, classify
from edacommon.ids import Clock
from edacommon.inbox import try_insert
from edacommon.logging import get_logger, log_context
from edacommon.metrics import EdaMetrics
from edacommon.serde import AvroSerde
from edacommon.tracing import consumer_span

log = get_logger(__name__)

IN_PLACE_ATTEMPTS = 5


class Outcome(StrEnum):
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    RETRY = "retry"
    DLQ = "dlq"


def backoff(attempt: int, *, base: float = 0.2, jitter: float = 0.2) -> float:
    """200 ms, 400 ms, 800 ms, 1.6 s, 3.2 s, each +/- 20 % (ADR-0007)."""
    delay = base * (2 ** (attempt - 1))
    return float(delay * (1 + random.uniform(-jitter, jitter)))  # noqa: S311 - jitter, not crypto


@dataclass(frozen=True, slots=True)
class ProcessResult:
    outcome: Outcome
    error: BaseException | None = None


class MessageProcessor:
    """Runs one record through dedupe, deserialisation, the handler and error routing."""

    def __init__(
        self,
        *,
        group: str,
        registry: HandlerRegistry,
        db: Database,
        serde: AvroSerde,
        forwarder: Forwarder,
        metrics: EdaMetrics,
        clock: Clock,
        sleep: Callable[[float], None] = time.sleep,
        in_place_attempts: int = IN_PLACE_ATTEMPTS,
    ) -> None:
        self.group = group
        self.registry = registry
        self._db = db
        self._serde = serde
        self._forwarder = forwarder
        self._metrics = metrics
        self._clock = clock
        self._sleep = sleep
        self._attempts = in_place_attempts

    def process(self, record: ConsumedRecord) -> ProcessResult:
        ce_type = record.event_type
        handler = self.registry.get(ce_type)
        etype = ce_type or "unknown"
        if handler is None:
            # Dispatch before deserialising: never decode a type we have no reader schema for.
            self._metrics.processed(
                topic=self._metric_topic(record), consumer_group=self.group, event_type=etype, outcome=Outcome.IGNORED
            )
            return ProcessResult(Outcome.IGNORED)

        last_exc: BaseException | None = None
        for attempt in range(1, self._attempts + 1):
            try:
                outcome = self._attempt(record, handler)
            except Exception as exc:
                cls = classify(exc)
                last_exc = exc
                if cls is Transient:
                    log.warning("transient failure, retrying in place", event_type=etype, attempt=attempt, error=exc)
                    self._sleep(backoff(attempt))
                    continue
                if cls is NonRetryable:
                    return self._to_dlq(record, etype, exc)
                return self._to_retry(record, etype, exc)
            self._metrics.processed(
                topic=self._metric_topic(record), consumer_group=self.group, event_type=etype, outcome=outcome
            )
            return ProcessResult(outcome)
        # In-place retries exhausted: hand over to the non-blocking retry topics.
        assert last_exc is not None
        return self._to_retry(record, etype, last_exc)

    # ------------------------------------------------------------------------------------------
    def _attempt(self, record: ConsumedRecord, handler: Handler) -> Outcome:
        headers = record.header_map
        event_id = record.event_id
        started = time.perf_counter()
        with self._db.unit_of_work() as uow:
            if event_id is not None and not try_insert(
                uow.session,
                message_id=event_id,
                consumer=self.group,
                message_type=handler.record_type,
                source_topic=record.topic,
                source_partition=record.partition,
                source_offset=record.offset,
            ):
                # Duplicate: the transaction holds nothing; leaving the block commits an empty tx.
                return Outcome.DUPLICATE
            if record.value is None:
                raise NonRetryable("tombstone on a topic with a registered handler")
            value = self._serde.deserialize(self._original_topic(record), handler.record_type, record.value)
            envelope = value.get("envelope") or {}
            if event_id is None:
                # No ce_id header (a producer that bypassed the outbox): fall back to the envelope.
                event_id = str(envelope.get("eventId"))
                if not try_insert(
                    uow.session,
                    message_id=event_id,
                    consumer=self.group,
                    message_type=handler.record_type,
                    source_topic=record.topic,
                    source_partition=record.partition,
                    source_offset=record.offset,
                ):
                    return Outcome.DUPLICATE
            ctx = MessageContext(
                topic=self._original_topic(record),
                partition=record.partition,
                offset=record.offset,
                key=record.key_str,
                event_id=event_id,
                event_type=handler.record_type,
                consumer_group=self.group,
                headers=headers,
                envelope=envelope,
                attempt=current_attempt(record),
            )
            try:
                msg = handler.decode(value)
            except Exception as exc:
                raise NonRetryable(f"cannot map {handler.record_type}: {exc}") from exc
            with (
                consumer_span(
                    topic=record.topic,
                    group=self.group,
                    event_type=handler.record_type,
                    message_id=event_id,
                    partition=record.partition,
                    offset=record.offset,
                    key=record.key_str,
                    headers=headers,
                ),
                caused_by(ctx.causation()),
                log_context(
                    correlation_id=ctx.correlation_id, event_id=event_id, event_type=handler.record_type, order_id=record.key_str
                ),
            ):
                handler.fn(msg, ctx, uow)
        self._metrics.handler_duration(
            consumer_group=self.group, event_type=handler.record_type, seconds=time.perf_counter() - started
        )
        occurred = ctx.occurred_at
        if occurred is not None:
            self._metrics.event_age(
                topic=ctx.topic,
                consumer_group=self.group,
                event_type=handler.record_type,
                seconds=(self._clock.now() - occurred).total_seconds(),
            )
        return Outcome.SUCCESS

    def _to_retry(self, record: ConsumedRecord, etype: str, exc: BaseException) -> ProcessResult:
        route = self._forwarder.topology.next_retry(record, self._clock.now())
        if route.topic == self._forwarder.topology.dlq:
            return self._to_dlq(record, etype, exc)
        log.warning("forwarding to retry topic", event_type=etype, retry_topic=route.topic, attempt=route.attempt, error=exc)
        self._forwarder.forward(record, route, error_class=type(exc).__name__, error_message=str(exc), now=self._clock.now())
        self._metrics.processed(
            topic=self._metric_topic(record), consumer_group=self.group, event_type=etype, outcome=Outcome.RETRY
        )
        return ProcessResult(Outcome.RETRY, exc)

    def _to_dlq(self, record: ConsumedRecord, etype: str, exc: BaseException) -> ProcessResult:
        route = self._forwarder.topology.to_dlq(record)
        log.error("forwarding to DLQ", event_type=etype, dlq_topic=route.topic, error=exc)
        self._forwarder.forward(record, route, error_class=type(exc).__name__, error_message=str(exc), now=self._clock.now())
        self._metrics.processed(
            topic=self._metric_topic(record), consumer_group=self.group, event_type=etype, outcome=Outcome.DLQ
        )
        self._metrics.dlq(consumer_group=self.group, event_type=etype, error_class=type(exc).__name__)
        return ProcessResult(Outcome.DLQ, exc)

    def _original_topic(self, record: ConsumedRecord) -> str:
        """Records on retry topics were serialised for their original topic (subject strategy)."""
        if self._forwarder.topology.is_retry_topic(record.topic):
            return record.header("x-original-topic") or record.topic
        return record.topic

    def _metric_topic(self, record: ConsumedRecord) -> str:
        return record.topic
