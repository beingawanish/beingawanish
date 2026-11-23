# ADR-0011: Observability with OpenTelemetry, Jaeger, Prometheus and Grafana

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** infra/otel/collector.yaml, infra/prometheus/, infra/grafana/, docs/implementation-guide.md "Metrics"

## Context

An order crosses nine processes, two languages and a broker. Without end-to-end tracing, "why did order X take 40 seconds?" is unanswerable. Without uniform metrics, dashboards would differ between the Python and Java builds, and we could not compare them. Asynchronous flows add a twist: the trace must survive the outbox, Debezium and Kafka, and consumer lag matters as much as request latency.

## Decision

- **OpenTelemetry everywhere.** Both languages use the OpenTelemetry SDK (Python: `opentelemetry-sdk` with FastAPI, SQLAlchemy and confluent-kafka instrumentation; Java: the OpenTelemetry Spring Boot starter or Java agent, with Micrometer bridged). Everything is exported over OTLP to the **OpenTelemetry Collector**.
- **Traces → Jaeger** locally (Tempo is a drop-in alternative; the collector exporter is the only change).
- **Metrics → Prometheus** via the collector's Prometheus exporter, plus **kafka-exporter** for consumer lag read directly from the brokers. **Grafana** has a provisioned dashboard (`infra/grafana/dashboards/eda-overview.json`) and alert rules encode the SLOs.
- **Trace propagation through the outbox.** The producer stores the current `traceparent`/`tracestate` in the outbox row and the envelope. Debezium copies them into Kafka headers. The consumer starts a `CONSUMER` span whose **parent** is the producer's span context (a link is also added, per messaging semantic conventions). One checkout produces one trace through every service.
- **Custom metrics with fixed names and buckets** (`eda.event.age`, `eda.consumer.processed`, `eda.dlq.messages`, `eda.saga.*`, `eda.claimcheck.object.size`) are created through the **OpenTelemetry metrics API in both languages**, not Micrometer, so names, units and bucket boundaries are identical. The contract is in the implementation guide.
- **HTTP RED metrics come from the collector's `spanmetrics` connector**, not from each framework's own HTTP metrics, which differ between FastAPI and Spring. This gives identical latency panels for both builds.
- **Logs** are JSON to stdout with `trace_id`, `span_id`, `correlation_id`, `event_id` fields. The collector accepts OTLP logs; locally they go to the debug exporter.
- Resource attribute `eda.impl=python|java` lets every panel split by implementation.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Vendor agents (Datadog, New Relic) | Turnkey | Lock-in; the template must run offline on a laptop |
| Micrometer for all Java metrics, Prometheus client for Python | Idiomatic per language | Names, units and histogram buckets diverge (Micrometer OTLP defaults to milliseconds); cross-language dashboards break |
| Zipkin / B3 propagation | Simple | W3C trace context is the standard and what both OTel SDKs default to |
| Consumer spans as new traces with links only | Matches one reading of the semantic conventions | Harder to follow one order end to end in Jaeger; we use parent + link |
| Loki for logs locally | Full log search | One more container; add it when needed (the collector already speaks OTLP) |

## Consequences

- Every library in the shared layer (outbox writer, consumer runtime, claim-check client) emits spans and metrics. Services get observability by using the library.
- Sampling: 100 % locally (`parentbased_always_on`). In production, head sampling at the edge (for example 10 %) plus tail sampling in the collector for errors and slow traces.
- High-cardinality labels are forbidden on metrics: never `orderId`, `customerId` or `eventId`. Those belong on spans and logs.
- The collector must not see personal data; it also deletes common PII attributes as a safety net (ADR-0013).

## Trade-offs

We gain one trace per order across languages and the broker, identical dashboards for both builds, and a vendor-neutral pipeline. We pay with more containers locally, instrumentation discipline in the shared libraries, and careful context propagation code that must be tested (it is in the test checklist).

## When to revisit

- The organisation runs a managed observability backend: change collector exporters only.
- Trace volume costs money: introduce tail sampling in the collector.
- The OpenTelemetry messaging semantic conventions settle on parent-versus-link for consumers in a way our tools render differently.
