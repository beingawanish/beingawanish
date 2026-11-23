package com.edacommerce.edacommon.tracing;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.testing.TestTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import io.opentelemetry.sdk.trace.data.SpanData;
import java.nio.charset.StandardCharsets;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.header.internals.RecordHeaders;
import org.junit.jupiter.api.Test;

class MessagingTracingTest {
  static final String PARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";

  @Test
  void consumerSpanHasTheProducerAsParentAndLinkAndMessagingAttributes() {
    TestTelemetry t = new TestTelemetry();
    MessagingTracing tracing = new MessagingTracing(t.openTelemetry());
    RecordHeaders headers = new RecordHeaders();
    headers.add("traceparent", PARENT.getBytes(StandardCharsets.UTF_8));
    ConsumerRecord<String, byte[]> r =
        new ConsumerRecord<>("payment.commands.v1", 2, 9L, "o1", new byte[0]);
    r.headers().add(headers.lastHeader("traceparent"));

    Context parent = tracing.extract(r.headers());
    Span span = tracing.startConsumerSpan(r, "payment-svc", "e1", parent);
    String inner;
    try (Scope s = span.makeCurrent()) {
      inner = MessagingTracing.current().traceparent();
    } finally {
      span.end();
    }

    SpanData d = t.spans().get(0);
    assertThat(d.getKind()).isEqualTo(SpanKind.CONSUMER);
    assertThat(d.getTraceId()).isEqualTo("4bf92f3577b34da6a3ce929d0e0e4736");
    assertThat(d.getParentSpanId()).isEqualTo("00f067aa0ba902b7");
    assertThat(d.getLinks()).hasSize(1);
    assertThat(d.getAttributes().asMap().toString())
        .contains(
            "messaging.system=kafka",
            "messaging.destination.name=payment.commands.v1",
            "messaging.kafka.consumer.group=payment-svc",
            "messaging.message.id=e1");
    assertThat(inner)
        .hasSize(55)
        .startsWith("00-4bf92f3577b34da6a3ce929d0e0e4736-")
        .isNotEqualTo(PARENT);
  }

  @Test
  void noCurrentSpanMeansNoTraceHeaders() {
    assertThat(MessagingTracing.current()).isEqualTo(MessagingTracing.TraceHeaders.NONE);
  }
}
