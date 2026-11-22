package com.edacommerce.edacommon.tracing;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.Headers;
import org.springframework.lang.Nullable;

/**
 * W3C trace context through the outbox and Kafka headers (ADR-0011). Only the W3C propagator is
 * used, never B3 or Jaeger (guide §5 rule 12), regardless of what the SDK's global propagators are.
 */
public class MessagingTracing {

  /** traceparent and tracestate of a span, as stored in outbox rows and envelopes. */
  public record TraceHeaders(@Nullable String traceparent, @Nullable String tracestate) {
    public static final TraceHeaders NONE = new TraceHeaders(null, null);
  }

  private static final W3CTraceContextPropagator W3C = W3CTraceContextPropagator.getInstance();

  private static final TextMapGetter<Headers> KAFKA_GETTER =
      new TextMapGetter<>() {
        @Override
        public Iterable<String> keys(Headers carrier) {
          return List.of(EdaHeaders.TRACEPARENT, EdaHeaders.TRACESTATE);
        }

        @Override
        @Nullable
        public String get(@Nullable Headers carrier, String key) {
          if (carrier == null) {
            return null;
          }
          Header h = carrier.lastHeader(key);
          return h == null || h.value() == null
              ? null
              : new String(h.value(), StandardCharsets.UTF_8);
        }
      };

  private final Tracer tracer;

  public MessagingTracing(OpenTelemetry openTelemetry) {
    this.tracer = openTelemetry.getTracer("com.edacommerce.edacommon");
  }

  public Context extract(Headers headers) {
    return W3C.extract(Context.root(), headers, KAFKA_GETTER);
  }

  /**
   * A CONSUMER span whose parent is the producer's context, plus a link to it (ADR-0011 chooses
   * parent + link so one order is one trace in Jaeger).
   */
  public Span startConsumerSpan(
      ConsumerRecord<?, ?> record, String consumerGroup, String eventId, Context parent) {
    SpanContext producer = Span.fromContext(parent).getSpanContext();
    var builder =
        tracer
            .spanBuilder(record.topic() + " process")
            .setSpanKind(SpanKind.CONSUMER)
            .setParent(parent)
            .setAttribute("messaging.system", "kafka")
            .setAttribute("messaging.operation", "process")
            .setAttribute("messaging.destination.name", record.topic())
            .setAttribute("messaging.kafka.consumer.group", consumerGroup)
            .setAttribute("messaging.kafka.destination.partition", (long) record.partition())
            .setAttribute("messaging.kafka.message.offset", record.offset())
            .setAttribute("messaging.message.id", eventId);
    if (producer.isValid()) {
      builder.addLink(producer);
    }
    return builder.startSpan();
  }

  /** A span for background work (sweepers, relays, webhooks processing) that starts a new trace. */
  public Span startInternalSpan(String name) {
    return tracer.spanBuilder(name).setSpanKind(SpanKind.INTERNAL).setNoParent().startSpan();
  }

  /** The current span's context in W3C form; NONE when there is no valid span. */
  public static TraceHeaders current() {
    if (!Span.current().getSpanContext().isValid()) {
      return TraceHeaders.NONE;
    }
    Map<String, String> carrier = new HashMap<>();
    W3C.inject(Context.current(), carrier, Map::put);
    String state = carrier.get(EdaHeaders.TRACESTATE);
    return new TraceHeaders(
        carrier.get(EdaHeaders.TRACEPARENT), state == null || state.isEmpty() ? null : state);
  }
}
