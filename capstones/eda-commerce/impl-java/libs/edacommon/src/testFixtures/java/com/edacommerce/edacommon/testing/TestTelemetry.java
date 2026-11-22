package com.edacommerce.edacommon.testing;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.metrics.SdkMeterProvider;
import io.opentelemetry.sdk.metrics.data.MetricData;
import io.opentelemetry.sdk.testing.exporter.InMemoryMetricReader;
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

/** An OpenTelemetry SDK with in-memory exporters, for asserting spans and the metric contract. */
public final class TestTelemetry {
  private final InMemoryMetricReader metrics = InMemoryMetricReader.create();
  private final InMemorySpanExporter spans = InMemorySpanExporter.create();
  private final OpenTelemetrySdk sdk;

  public TestTelemetry() {
    sdk =
        OpenTelemetrySdk.builder()
            .setTracerProvider(
                SdkTracerProvider.builder().addSpanProcessor(SimpleSpanProcessor.create(spans)).build())
            .setMeterProvider(SdkMeterProvider.builder().registerMetricReader(metrics).build())
            .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
            .build();
  }

  public OpenTelemetry openTelemetry() {
    return sdk;
  }

  public Collection<MetricData> collectMetrics() {
    return metrics.collectAllMetrics();
  }

  public Optional<MetricData> metric(String name) {
    return collectMetrics().stream().filter(m -> m.getName().equals(name)).findFirst();
  }

  public List<SpanData> spans() {
    return spans.getFinishedSpanItems();
  }

  public void reset() {
    spans.reset();
  }
}
