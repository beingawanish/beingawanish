"""confluent-kafka poll loops for the main consumer and the retry consumer (guide §4.1, ADR-0007).

Main consumer (group ``G``): subscribes to the service's topics and runs every record through the
:class:`~edacommon.consumer.processor.MessageProcessor`.

Retry consumer (group ``G-retry``): subscribes to ``G.retry.10s|1m|10m``. A record whose
``x-not-before`` lies in the future pauses its partition and rewinds to it; the partition resumes
when the time has come. The same processor (and so the same handlers and the same inbox consumer
name ``G``) handles it.

Offsets: a record is "done" once ``process`` returned (DB committed, or forward acknowledged).
Done offsets are committed asynchronously every second or 500 records, and synchronously on
partition revoke and on shutdown. One record at a time per partition; parallelism comes from
partitions (and from running several loop threads or processes in the same group).
"""

from __future__ import annotations

import contextlib
import threading
import time
from datetime import datetime
from typing import Any

from confluent_kafka import Consumer, KafkaError, KafkaException, TopicPartition

from edacommon.consumer.forwarder import X_NOT_BEFORE
from edacommon.consumer.processor import MessageProcessor
from edacommon.consumer.record import ConsumedRecord
from edacommon.ids import Clock
from edacommon.logging import get_logger

log = get_logger(__name__)

COMMIT_INTERVAL_S = 1.0
COMMIT_EVERY_N = 500
BATCH_SIZE = 100  # guide §7.1: small batches keep commit latency low


def parse_rfc3339(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class ConsumerLoop:
    """One consumer thread. ``retry_mode`` makes it honour ``x-not-before``."""

    def __init__(
        self,
        *,
        consumer_conf: dict[str, Any],
        topics: list[str],
        processor: MessageProcessor,
        clock: Clock,
        retry_mode: bool = False,
        name: str = "consumer",
        consumer_factory: Any = Consumer,
    ) -> None:
        self._conf = consumer_conf
        self._topics = topics
        self._processor = processor
        self._clock = clock
        self._retry_mode = retry_mode
        self._factory = consumer_factory
        self.name = name
        self._stop = threading.Event()
        self._consumer: Any = None
        self._done: dict[tuple[str, int], int] = {}
        self._since_commit = 0
        self._last_commit = time.monotonic()
        self._paused_until: dict[tuple[str, int], datetime] = {}
        self.assigned = threading.Event()
        self.subscribed = threading.Event()
        self.processed_count = 0

    # ------------------------------------------------------------------------------- lifecycle
    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def run(self) -> None:
        self._consumer = self._factory(self._conf)
        self._consumer.subscribe(self._topics, on_assign=self._on_assign, on_revoke=self._on_revoke, on_lost=self._on_lost)
        self.subscribed.set()
        log.info("consumer started", consumer=self.name, topics=self._topics, group=self._conf["group.id"])
        try:
            while not self._stop.is_set():
                self._resume_due()
                msgs = self._consumer.consume(num_messages=BATCH_SIZE, timeout=0.5)
                for msg in msgs:
                    if self._stop.is_set():
                        # Not processed: not marked done, so the next owner reads it again.
                        break
                    if msg.error():
                        self._handle_error(msg.error())
                        continue
                    tp = (msg.topic(), msg.partition())
                    if tp in self._paused_until:
                        continue  # prefetched before the pause; will be re-read after the rewind
                    self._handle(ConsumedRecord.from_kafka(msg))
                self._maybe_commit()
        finally:
            self._shutdown()

    def _shutdown(self) -> None:
        try:
            self._commit(sync=True)
        except Exception as exc:  # pragma: no cover - broker gone at shutdown
            log.warning("final commit failed", consumer=self.name, error=exc)
        try:
            self._consumer.close()
        except Exception as exc:  # pragma: no cover
            log.warning("consumer close failed", consumer=self.name, error=exc)
        log.info("consumer stopped", consumer=self.name, processed=self.processed_count)

    # -------------------------------------------------------------------------------- records
    def _handle(self, record: ConsumedRecord) -> None:
        tp = (record.topic, record.partition)
        if self._retry_mode:
            nb = record.header(X_NOT_BEFORE)
            not_before = parse_rfc3339(nb) if nb else None
            if not_before and not_before > self._clock.now():
                self._pause_until(record, not_before)
                return
        while not self._stop.is_set():
            try:
                self._processor.process(record)
                break
            except Exception as exc:
                # Only a failed forward (or a bug in the runtime) gets here. The record is not
                # done; keep the partition position and try again shortly.
                log.error(
                    "record not processed; retrying",
                    consumer=self.name,
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                    error=exc,
                )
                self._stop.wait(1.0)
        else:
            # Stopping in the middle of a retry: rewind so the record is not skipped.
            self._seek(record)
            return
        self._done[tp] = record.offset + 1
        self._since_commit += 1
        self.processed_count += 1

    def _pause_until(self, record: ConsumedRecord, when: datetime) -> None:
        tp = TopicPartition(record.topic, record.partition, record.offset)
        self._consumer.pause([tp])
        self._consumer.seek(tp)
        self._paused_until[(record.topic, record.partition)] = when

    def _resume_due(self) -> None:
        if not self._paused_until:
            return
        now = self._clock.now()
        due = [tp for tp, when in self._paused_until.items() if when <= now]
        if due:
            self._consumer.resume([TopicPartition(t, p) for t, p in due])
            for tp in due:
                del self._paused_until[tp]

    def _seek(self, record: ConsumedRecord) -> None:
        with contextlib.suppress(KafkaException):
            self._consumer.seek(TopicPartition(record.topic, record.partition, record.offset))

    def _handle_error(self, err: KafkaError) -> None:
        if err.code() == KafkaError._PARTITION_EOF:
            return
        if err.fatal():
            log.error("fatal consumer error", consumer=self.name, error=str(err))
            raise KafkaException(err)
        log.warning("consumer error", consumer=self.name, error=str(err))

    # -------------------------------------------------------------------------------- offsets
    def _maybe_commit(self) -> None:
        if self._since_commit >= COMMIT_EVERY_N or (self._done and time.monotonic() - self._last_commit >= COMMIT_INTERVAL_S):
            self._commit(sync=False)

    def _commit(self, *, sync: bool, only: list[tuple[str, int]] | None = None) -> None:
        if self._consumer is None:
            return
        keys = only if only is not None else list(self._done)
        offsets = [TopicPartition(t, p, self._done[(t, p)]) for t, p in keys if (t, p) in self._done]
        if not offsets:
            return
        try:
            self._consumer.commit(offsets=offsets, asynchronous=not sync)
        except KafkaException as exc:
            if exc.args and exc.args[0].code() == KafkaError._NO_OFFSET:
                return
            raise
        for t, p in keys:
            self._done.pop((t, p), None)
        self._since_commit = 0
        self._last_commit = time.monotonic()

    def _on_assign(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        log.info("partitions assigned", consumer=self.name, partitions=[f"{p.topic}[{p.partition}]" for p in partitions])
        self.assigned.set()

    def _on_revoke(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        # The in-flight record has finished (callbacks run inside poll), so commit and release.
        keys = [(p.topic, p.partition) for p in partitions]
        try:
            self._commit(sync=True, only=keys)
        except Exception as exc:
            log.warning("commit on revoke failed", consumer=self.name, error=exc)
        for k in keys:
            self._paused_until.pop(k, None)
        log.info("partitions revoked", consumer=self.name, partitions=[f"{t}[{p}]" for t, p in keys])

    def _on_lost(self, consumer: Any, partitions: list[TopicPartition]) -> None:
        for p in partitions:
            self._done.pop((p.topic, p.partition), None)
            self._paused_until.pop((p.topic, p.partition), None)
        log.warning("partitions lost", consumer=self.name, count=len(partitions))
