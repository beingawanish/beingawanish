"""W3C trace context through outbox rows and Kafka headers (guide §4 ``tracing``, ADR-0011).

* Producer side: :func:`current_trace_headers` returns the ``traceparent``/``tracestate`` of the active
  span. The outbox writer stores them in the row and the envelope; Debezium copies them to headers.
* Consumer side: :func:`consumer_span` starts a ``CONSUMER`` span whose **parent** is the context
  extracted from the record headers, plus a **link** to the same context (OTel messaging semantic
  conventions), with ``messaging.*`` attributes.

Only the W3C propagator is used (guide §5 rule 12): no B3, no Jaeger headers.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.propagators.textmap import DefaultGetter
from opentelemetry.trace import Link, Span, SpanKind
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()
_GETTER = DefaultGetter()
TRACER_NAME = "edacommon"


def tracer() -> trace.Tracer:
    return trace.get_tracer(TRACER_NAME)


def current_trace_headers() -> tuple[str | None, str | None]:
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get("traceparent"), carrier.get("tracestate") or None


def extract(headers: Mapping[str, str | None]) -> otel_context.Context:
    carrier = {k: v for k, v in headers.items() if v is not None and k in ("traceparent", "tracestate")}
    return _PROPAGATOR.extract(carrier, getter=_GETTER)


@contextmanager
def consumer_span(
    *,
    topic: str,
    group: str,
    event_type: str,
    message_id: str | None,
    partition: int,
    offset: int,
    key: str | None,
    headers: Mapping[str, str | None],
) -> Iterator[Span]:
    parent_ctx = extract(headers)
    parent_span_ctx = trace.get_current_span(parent_ctx).get_span_context()
    links = [Link(parent_span_ctx)] if parent_span_ctx.is_valid else []
    attrs: dict[str, Any] = {
        "messaging.system": "kafka",
        "messaging.operation.type": "process",
        "messaging.destination.name": topic,
        "messaging.kafka.consumer.group": group,
        "messaging.consumer.group.name": group,
        "messaging.destination.partition.id": str(partition),
        "messaging.kafka.offset": offset,
        "eda.event_type": event_type,
    }
    if message_id:
        attrs["messaging.message.id"] = message_id
    if key is not None:
        attrs["messaging.kafka.message.key"] = key
    with tracer().start_as_current_span(
        f"process {topic}", context=parent_ctx, kind=SpanKind.CONSUMER, links=links, attributes=attrs
    ) as span:
        yield span


def current_ids() -> tuple[str | None, str | None]:
    """Hex trace id and span id of the active span, for log records."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None, None
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


def setup_tracing(
    service_name: str, resource_attributes: Mapping[str, Any], *, endpoint: str, protocol: str, disabled: bool = False
) -> None:
    """Install the SDK tracer provider with an OTLP exporter. Safe to call once per process."""
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    set_global_textmap(_PROPAGATOR)
    provider = TracerProvider(resource=Resource.create(dict(resource_attributes)))
    if not disabled:
        if protocol == "grpc":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        else:  # pragma: no cover - http/protobuf exporter is optional
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[no-redef]
                OTLPSpanExporter,
            )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
