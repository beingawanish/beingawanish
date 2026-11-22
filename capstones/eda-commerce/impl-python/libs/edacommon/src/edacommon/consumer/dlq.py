"""DLQ peek and replay for ``GET /ops/dlq`` and ``POST /ops/dlq/replay`` (admin.yaml, ADR-0007).

Kafka cannot delete a message, so "what is still parked" is tracked with a dedicated consumer group
``<G>-dlq-ops``: everything after its committed offset is pending. Replay forwards matching records
to ``<G>.retry.10s`` (only this group sees them again) with ``x-retry-attempt=1`` and
``x-not-before=now``, then advances the committed offset over the contiguous prefix it handled.
Records skipped by a filter stay pending and keep showing up in ``GET /ops/dlq``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from confluent_kafka import OFFSET_BEGINNING, Consumer, TopicPartition

from edacommon.consumer.forwarder import (
    X_ERROR_CLASS,
    X_ERROR_MESSAGE,
    X_ORIGINAL_OFFSET,
    X_ORIGINAL_PARTITION,
    X_ORIGINAL_TOPIC,
    X_RETRY_ATTEMPT,
    RetryRoute,
    RetryTopology,
    forwarded_headers,
)
from edacommon.consumer.record import ConsumedRecord
from edacommon.ids import Clock, rfc3339
from edacommon.outbox import Publisher, produce_and_wait


@dataclass(frozen=True, slots=True)
class DlqEntry:
    eventId: str | None  # noqa: N815 - API field names (admin.yaml DlqEntry)
    eventType: str | None  # noqa: N815
    originalTopic: str | None  # noqa: N815
    originalPartition: int | None  # noqa: N815
    originalOffset: int | None  # noqa: N815
    attempts: int
    errorClass: str | None  # noqa: N815
    errorMessage: str | None  # noqa: N815
    failedAt: str | None  # noqa: N815

    @classmethod
    def of(cls, r: ConsumedRecord) -> DlqEntry:
        h = r.header_map

        def as_int(v: str | None) -> int | None:
            try:
                return int(v) if v is not None else None
            except ValueError:
                return None

        return cls(
            eventId=r.event_id,
            eventType=r.event_type,
            originalTopic=h.get(X_ORIGINAL_TOPIC),
            originalPartition=as_int(h.get(X_ORIGINAL_PARTITION)),
            originalOffset=as_int(h.get(X_ORIGINAL_OFFSET)),
            attempts=as_int(h.get(X_RETRY_ATTEMPT)) or 0,
            errorClass=h.get(X_ERROR_CLASS),
            errorMessage=h.get(X_ERROR_MESSAGE),
            failedAt=rfc3339(r.timestamp) if r.timestamp else None,
        )


class DlqOps:
    def __init__(
        self,
        *,
        consumer_conf: dict[str, Any],
        producer: Publisher,
        group: str,
        clock: Clock,
        consumer_factory: Callable[[dict[str, Any]], Any] = Consumer,
    ) -> None:
        self._topology = RetryTopology(group)
        self._group = group
        self._ops_group = f"{group}-dlq-ops"
        self._conf = {**consumer_conf, "group.id": self._ops_group, "enable.auto.commit": False}
        self._producer = producer
        self._clock = clock
        self._factory = consumer_factory

    def _scan(self, limit: int, timeout: float = 5.0) -> tuple[Any, list[ConsumedRecord]]:
        c = self._factory(self._conf)
        md = c.list_topics(self._topology.dlq, timeout=timeout)
        topic_md = md.topics.get(self._topology.dlq)
        if topic_md is None or topic_md.error is not None:
            c.close()
            return None, []
        parts = [TopicPartition(self._topology.dlq, p) for p in topic_md.partitions]
        committed = c.committed(parts, timeout=timeout)
        starts: list[TopicPartition] = []
        ends: dict[int, int] = {}
        for tp in committed:
            low, high = c.get_watermark_offsets(TopicPartition(tp.topic, tp.partition), timeout=timeout)
            start = tp.offset if tp.offset >= 0 else OFFSET_BEGINNING
            if (tp.offset if tp.offset >= 0 else low) < high:
                starts.append(TopicPartition(tp.topic, tp.partition, start))
                ends[tp.partition] = high
        if not starts:
            return c, []
        c.assign(starts)
        out: list[ConsumedRecord] = []
        deadline = time.monotonic() + timeout
        done: set[int] = set()
        while len(out) < limit and len(done) < len(ends) and time.monotonic() < deadline:
            for m in c.consume(num_messages=min(500, limit - len(out)), timeout=0.5):
                if m.error() or m.partition() in done:
                    continue
                out.append(ConsumedRecord.from_kafka(m))
                if m.offset() + 1 >= ends[m.partition()]:
                    done.add(m.partition())
        out.sort(key=lambda r: (r.partition, r.offset))
        return c, out[:limit]

    def peek(self, limit: int = 50) -> list[DlqEntry]:
        c, records = self._scan(min(limit, 500))
        if c is not None:
            c.close()
        return [DlqEntry.of(r) for r in records]

    def replay(self, *, max_messages: int = 100, event_type: str | None = None, event_ids: list[str] | None = None) -> int:
        c, records = self._scan(min(max_messages, 10000) if not (event_type or event_ids) else 10000)
        if c is None:
            return 0
        wanted = set(event_ids or [])
        replayed = 0
        commit: dict[int, int] = {}
        blocked: set[int] = set()
        now: datetime = self._clock.now()
        try:
            for r in records:
                if replayed >= max_messages:
                    break
                matches = (event_type is None or r.event_type == event_type) and (not wanted or (r.event_id in wanted))
                if not matches:
                    blocked.add(r.partition)  # leave it pending; stop advancing this partition
                    continue
                headers = forwarded_headers(
                    r,
                    group=self._group,
                    attempt=1,
                    not_before=now,
                    error_class=r.header(X_ERROR_CLASS) or "Replayed",
                    error_message=r.header(X_ERROR_MESSAGE) or "",
                    now=now,
                )
                route = RetryRoute(self._topology.retry[0], 1, now)
                produce_and_wait(self._producer, [(route.topic, r.key, r.value, headers)])
                replayed += 1
                if r.partition not in blocked:
                    commit[r.partition] = r.offset + 1
            if commit:
                c.commit(offsets=[TopicPartition(self._topology.dlq, p, o) for p, o in commit.items()], asynchronous=False)
        finally:
            c.close()
        return replayed
