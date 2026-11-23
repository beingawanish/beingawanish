"""Forwarding to ``<group>.retry.*`` and ``<group>.dlq`` (ADR-0007, architecture §8.1).

Forwarding copies the **original key and value bytes unchanged** and the original headers, then sets
the ``x-*`` headers. It never re-serialises, so retry and DLQ topics need no schema subjects.
``x-original-*`` always describe the first failure's source record, even after several hops.

Header formats (UTF-8 strings): ``x-retry-attempt`` decimal; ``x-original-partition`` /
``x-original-offset`` decimal; ``x-not-before`` RFC 3339 UTC with milliseconds and ``Z``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from contracts_py.topics import RETRY_DELAY_SECONDS, dlq_topic, retry_topics

from edacommon.consumer.record import ConsumedRecord
from edacommon.ids import rfc3339
from edacommon.outbox import Publisher, produce_and_wait

X_RETRY_ATTEMPT = "x-retry-attempt"
X_ORIGINAL_TOPIC = "x-original-topic"
X_ORIGINAL_PARTITION = "x-original-partition"
X_ORIGINAL_OFFSET = "x-original-offset"
X_NOT_BEFORE = "x-not-before"
X_ERROR_CLASS = "x-error-class"
X_ERROR_MESSAGE = "x-error-message"
X_FAILED_CONSUMER_GROUP = "x-failed-consumer-group"
X_HEADERS = (
    X_RETRY_ATTEMPT,
    X_ORIGINAL_TOPIC,
    X_ORIGINAL_PARTITION,
    X_ORIGINAL_OFFSET,
    X_NOT_BEFORE,
    X_ERROR_CLASS,
    X_ERROR_MESSAGE,
    X_FAILED_CONSUMER_GROUP,
)
MAX_ERROR_MESSAGE = 512


@dataclass(frozen=True, slots=True)
class RetryRoute:
    topic: str
    attempt: int
    not_before: datetime | None


class RetryTopology:
    """Where a failed record of group ``G`` goes next."""

    def __init__(self, group: str) -> None:
        self.group = group
        self.retry = retry_topics(group)
        self.dlq = dlq_topic(group)
        self.delays = tuple(timedelta(seconds=s) for s in RETRY_DELAY_SECONDS)

    def is_retry_topic(self, topic: str) -> bool:
        return topic in self.retry

    def next_retry(self, record: ConsumedRecord, now: datetime) -> RetryRoute:
        """Main topic -> retry.10s; retry.10s -> retry.1m; retry.1m -> retry.10m; retry.10m -> dlq."""
        attempt = current_attempt(record) + 1
        idx = self.retry.index(record.topic) + 1 if record.topic in self.retry else 0
        if idx >= len(self.retry):
            return RetryRoute(self.dlq, attempt - 1, None)
        return RetryRoute(self.retry[idx], attempt, now + self.delays[idx])

    def to_dlq(self, record: ConsumedRecord) -> RetryRoute:
        return RetryRoute(self.dlq, current_attempt(record), None)


def current_attempt(record: ConsumedRecord) -> int:
    raw = record.header(X_RETRY_ATTEMPT)
    try:
        return int(raw) if raw else 0
    except ValueError:
        return 0


def forwarded_headers(
    record: ConsumedRecord,
    *,
    group: str,
    attempt: int,
    not_before: datetime | None,
    error_class: str,
    error_message: str,
    now: datetime,
) -> list[tuple[str, bytes | None]]:
    existing = record.header_map
    headers: list[tuple[str, bytes | None]] = [(k, v) for k, v in record.headers if k not in X_HEADERS]

    def put(name: str, value: str) -> None:
        headers.append((name, value.encode("utf-8")))

    put(X_RETRY_ATTEMPT, str(attempt))
    put(X_ORIGINAL_TOPIC, existing.get(X_ORIGINAL_TOPIC) or record.topic)
    put(X_ORIGINAL_PARTITION, existing.get(X_ORIGINAL_PARTITION) or str(record.partition))
    put(X_ORIGINAL_OFFSET, existing.get(X_ORIGINAL_OFFSET) or str(record.offset))
    put(X_NOT_BEFORE, rfc3339(not_before or now))
    put(X_ERROR_CLASS, error_class)
    put(X_ERROR_MESSAGE, error_message[:MAX_ERROR_MESSAGE])
    put(X_FAILED_CONSUMER_GROUP, group)
    return headers


class Forwarder:
    """Publishes a record to a retry or DLQ topic and waits for the broker's acknowledgement."""

    def __init__(self, producer: Publisher, group: str) -> None:
        self._producer = producer
        self.topology = RetryTopology(group)

    def forward(self, record: ConsumedRecord, route: RetryRoute, *, error_class: str, error_message: str, now: datetime) -> None:
        headers = forwarded_headers(
            record,
            group=self.topology.group,
            attempt=route.attempt,
            not_before=route.not_before,
            error_class=error_class,
            error_message=error_message,
            now=now,
        )
        # Key and value bytes are passed through untouched (ADR-0007).
        produce_and_wait(self._producer, [(route.topic, record.key, record.value, headers)])
