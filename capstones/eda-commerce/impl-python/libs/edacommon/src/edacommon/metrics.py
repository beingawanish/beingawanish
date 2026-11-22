"""The metric contract of guide §8, created through the OpenTelemetry metrics API (ADR-0011).

Names, units, attribute keys and histogram boundaries are fixed: the Java build emits the same, and
the Grafana dashboard and alert rules query the Prometheus names. Histogram boundaries are applied
with SDK views (:func:`views`), so whoever builds the ``MeterProvider`` must pass them.

Never pass ids (orderId, eventId, customerId) as attributes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from opentelemetry.metrics import Meter, MeterProvider, NoOpMeterProvider

EVENT_AGE = "eda.event.age"
CONSUMER_PROCESSED = "eda.consumer.processed"
HANDLER_DURATION = "eda.consumer.handler.duration"
DLQ_MESSAGES = "eda.dlq.messages"
OUTBOX_PENDING = "eda.outbox.pending"
SAGA_OUTCOMES = "eda.saga.outcomes"
SAGA_DURATION = "eda.saga.duration"
SAGA_STEP_DURATION = "eda.saga.step.duration"
SAGA_STEP_TIMEOUTS = "eda.saga.step.timeouts"
SAGA_OVERDUE = "eda.saga.overdue"
CLAIMCHECK_SIZE = "eda.claimcheck.object.size"
WEBHOOK_RECEIVED = "eda.webhook.received"

BUCKETS: dict[str, tuple[float, ...]] = {
    EVENT_AGE: (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 300, 1800),
    HANDLER_DURATION: (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    SAGA_DURATION: (1, 5, 10, 30, 60, 300, 900, 3600, 21600, 86400, 604800, 2592000),
    SAGA_STEP_DURATION: (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120, 240, 600),
    CLAIMCHECK_SIZE: (1e3, 1e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 5e6, 2e7),
}

# OTel name -> Prometheus name exposed by the collector (for tests and docs).
PROMETHEUS_NAMES: dict[str, str] = {
    EVENT_AGE: "eda_event_age_seconds",
    CONSUMER_PROCESSED: "eda_consumer_processed_total",
    HANDLER_DURATION: "eda_consumer_handler_duration_seconds",
    DLQ_MESSAGES: "eda_dlq_messages_total",
    OUTBOX_PENDING: "eda_outbox_pending",
    SAGA_OUTCOMES: "eda_saga_outcomes_total",
    SAGA_DURATION: "eda_saga_duration_seconds",
    SAGA_STEP_DURATION: "eda_saga_step_duration_seconds",
    SAGA_STEP_TIMEOUTS: "eda_saga_step_timeouts_total",
    SAGA_OVERDUE: "eda_saga_overdue",
    CLAIMCHECK_SIZE: "eda_claimcheck_object_size_bytes",
    WEBHOOK_RECEIVED: "eda_webhook_received_total",
}

OUTCOMES = ("success", "duplicate", "ignored", "retry", "dlq")


def views() -> list[Any]:
    """SDK views that pin the histogram boundaries of guide §8."""
    from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View

    return [
        View(instrument_name=name, aggregation=ExplicitBucketHistogramAggregation(boundaries=list(b)))
        for name, b in BUCKETS.items()
    ]


class EdaMetrics:
    """Pre-registered instruments. One instance per process (or per test)."""

    def __init__(self, provider: MeterProvider | None = None) -> None:
        meter: Meter = (provider or NoOpMeterProvider()).get_meter("edacommon", "1")
        self._event_age = meter.create_histogram(EVENT_AGE, unit="s", description="Now minus envelope.occurredAt at the consumer")
        self._processed = meter.create_counter(CONSUMER_PROCESSED, unit="{message}", description="Records handled by outcome")
        self._handler = meter.create_histogram(HANDLER_DURATION, unit="s", description="Handler time inside the unit of work")
        self._dlq = meter.create_counter(DLQ_MESSAGES, unit="{message}", description="Records forwarded to the DLQ")
        self._outbox_pending = meter.create_gauge(OUTBOX_PENDING, unit="{row}", description="Unpublished outbox rows (polling relay)")
        self._saga_outcomes = meter.create_counter(SAGA_OUTCOMES, unit="{saga}", description="Sagas reaching an outcome")
        self._saga_duration = meter.create_histogram(SAGA_DURATION, unit="s", description="Saga start to terminal state")
        self._saga_step = meter.create_histogram(SAGA_STEP_DURATION, unit="s", description="Time spent per saga step")
        self._saga_timeouts = meter.create_counter(SAGA_STEP_TIMEOUTS, unit="{timeout}", description="Saga step deadlines fired")
        self._saga_overdue = meter.create_gauge(SAGA_OVERDUE, unit="{saga}", description="Sagas past deadline + 60 s")
        self._cc_size = meter.create_histogram(CLAIMCHECK_SIZE, unit="By", description="Claim-check object sizes")
        self._webhooks = meter.create_counter(WEBHOOK_RECEIVED, unit="{webhook}", description="Inbound webhooks by outcome")

    def event_age(self, *, topic: str, consumer_group: str, event_type: str, seconds: float) -> None:
        self._event_age.record(max(seconds, 0.0), {"topic": topic, "consumer_group": consumer_group, "event_type": event_type})

    def processed(self, *, topic: str, consumer_group: str, event_type: str, outcome: str) -> None:
        assert outcome in OUTCOMES, outcome
        self._processed.add(1, {"topic": topic, "consumer_group": consumer_group, "event_type": event_type, "outcome": outcome})

    def handler_duration(self, *, consumer_group: str, event_type: str, seconds: float) -> None:
        self._handler.record(seconds, {"consumer_group": consumer_group, "event_type": event_type})

    def dlq(self, *, consumer_group: str, event_type: str, error_class: str) -> None:
        self._dlq.add(1, {"consumer_group": consumer_group, "event_type": event_type, "error_class": error_class})

    def outbox_pending(self, rows: int) -> None:
        self._outbox_pending.set(rows)

    def saga_outcome(self, *, saga_type: str, outcome: str) -> None:
        self._saga_outcomes.add(1, {"saga_type": saga_type, "outcome": outcome})

    def saga_duration(self, *, saga_type: str, outcome: str, seconds: float) -> None:
        self._saga_duration.record(seconds, {"saga_type": saga_type, "outcome": outcome})

    def saga_step_duration(self, *, saga_type: str, step: str, seconds: float) -> None:
        self._saga_step.record(max(seconds, 0.0), {"saga_type": saga_type, "step": step})

    def saga_step_timeout(self, *, saga_type: str, state: str) -> None:
        self._saga_timeouts.add(1, {"saga_type": saga_type, "state": state})

    def saga_overdue(self, *, saga_type: str, count: int) -> None:
        self._saga_overdue.set(count, {"saga_type": saga_type})

    def claimcheck_size(self, *, bucket: str, direction: str, size: int) -> None:
        self._cc_size.record(size, {"bucket": bucket, "direction": direction})

    def webhook(self, *, source: str, outcome: str) -> None:
        self._webhooks.add(1, {"source": source, "outcome": outcome})


def setup_metrics(resource_attributes: dict[str, Any], *, endpoint: str, disabled: bool = False,
                  extra_readers: Sequence[Any] = ()) -> Any:
    """Build the SDK MeterProvider with the bucket views and an OTLP exporter; set it global."""
    from opentelemetry import metrics as otel_metrics
    from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    readers = list(extra_readers)
    if not disabled:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

        readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint), export_interval_millis=10000))
    provider = SdkMeterProvider(resource=Resource.create(resource_attributes), metric_readers=readers, views=views())
    otel_metrics.set_meter_provider(provider)
    return provider
