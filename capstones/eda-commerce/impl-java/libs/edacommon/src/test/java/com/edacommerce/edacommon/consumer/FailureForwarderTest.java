package com.edacommerce.edacommon.consumer;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.errors.TransientException;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.testing.TestTelemetry;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.MockProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.internals.RecordHeaders;
import org.apache.kafka.common.record.TimestampType;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.KafkaTemplate;
import com.edacommerce.edacommon.testing.KeepOpenMockProducer;
import org.springframework.kafka.mock.MockProducerFactory;

/** Checklist: RetryLater lands on G.retry.10s with all x-* headers and raw bytes unchanged. */
class FailureForwarderTest {
  static final Instant NOW = Instant.parse("2026-11-18T09:46:40.123Z");
  final MockProducer<String, byte[]> producer = KeepOpenMockProducer.create();
  final TestTelemetry telemetry = new TestTelemetry();
  final FailureForwarder forwarder =
      new FailureForwarder(
          new KafkaTemplate<>(new MockProducerFactory<>(() -> producer)),
          "payment-svc",
          new EdaMetrics(telemetry.openTelemetry()),
          Clock.fixed(NOW, ZoneOffset.UTC));
  final byte[] value = {0, 0, 0, 0, 7, 42, 43, 44};

  ConsumerRecord<String, byte[]> record(String topic, RecordHeaders headers) {
    return new ConsumerRecord<>(
        topic, 3, 1234L, 0L, TimestampType.CREATE_TIME, 0, 0, "order-1", value, headers, java.util.Optional.empty());
  }

  RecordHeaders original() {
    RecordHeaders h = new RecordHeaders();
    h.add(EdaHeaders.CE_ID, "e1".getBytes(StandardCharsets.UTF_8));
    h.add(EdaHeaders.CE_TYPE, "com.edacommerce.payment.AuthorizePayment".getBytes(StandardCharsets.UTF_8));
    h.add(EdaHeaders.TRACEPARENT, "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01".getBytes(StandardCharsets.UTF_8));
    return h;
  }

  @Test
  void retryLaterGoesToTheFirstRetryTopicWithBytesAndHeaders() {
    forwarder.accept(record("payment.commands.v1", original()), null, new RetryLaterException("psp degraded"));

    ProducerRecord<String, byte[]> sent = producer.history().get(0);
    assertThat(sent.topic()).isEqualTo("payment-svc.retry.10s");
    assertThat(sent.key()).isEqualTo("order-1");
    assertThat(sent.value()).isEqualTo(value);
    assertThat(names(sent))
        .containsExactly(
            "ce_id", "ce_type", "traceparent",
            "x-retry-attempt", "x-original-topic", "x-original-partition", "x-original-offset",
            "x-not-before", "x-error-class", "x-error-message", "x-failed-consumer-group");
    assertThat(header(sent, "x-retry-attempt")).isEqualTo("1");
    assertThat(header(sent, "x-original-topic")).isEqualTo("payment.commands.v1");
    assertThat(header(sent, "x-original-partition")).isEqualTo("3");
    assertThat(header(sent, "x-original-offset")).isEqualTo("1234");
    assertThat(header(sent, "x-not-before")).isEqualTo("2026-11-18T09:46:50.123Z");
    assertThat(header(sent, "x-error-class")).isEqualTo("RetryLaterException");
    assertThat(header(sent, "x-error-message")).isEqualTo("psp degraded");
    assertThat(header(sent, "x-failed-consumer-group")).isEqualTo("payment-svc");
    assertThat(telemetry.metric("eda.consumer.processed")).isPresent();
  }

  @Test
  void secondHopKeepsTheOriginalCoordinatesAndOneValuePerHeader() {
    forwarder.accept(record("payment.commands.v1", original()), null, new RetryLaterException("a"));
    ProducerRecord<String, byte[]> first = producer.history().get(0);
    RecordHeaders hop = new RecordHeaders(first.headers().toArray());
    forwarder.accept(record("payment-svc.retry.10s", hop), null, new TransientException("still down"));

    ProducerRecord<String, byte[]> second = producer.history().get(1);
    assertThat(second.topic()).isEqualTo("payment-svc.retry.1m");
    assertThat(header(second, "x-retry-attempt")).isEqualTo("2");
    assertThat(header(second, "x-original-topic")).isEqualTo("payment.commands.v1");
    assertThat(header(second, "x-original-offset")).isEqualTo("1234");
    assertThat(header(second, "x-not-before")).isEqualTo("2026-11-18T09:47:40.123Z");
    assertThat(names(second).stream().filter(n -> n.equals("x-retry-attempt"))).hasSize(1);
    assertThat(second.value()).isEqualTo(value);
  }

  @Test
  void nonRetryableAndExhaustedRetriesGoToTheDlq() {
    forwarder.accept(record("payment.commands.v1", original()), null, new NonRetryableException("bad"));
    assertThat(producer.history().get(0).topic()).isEqualTo("payment-svc.dlq");

    RecordHeaders third = original();
    third.add(EdaHeaders.X_RETRY_ATTEMPT, "3".getBytes(StandardCharsets.UTF_8));
    forwarder.accept(record("payment-svc.retry.10m", third), null, new RetryLaterException("x"));
    ProducerRecord<String, byte[]> parked = producer.history().get(1);
    assertThat(parked.topic()).isEqualTo("payment-svc.dlq");
    assertThat(header(parked, "x-retry-attempt")).isEqualTo("4");
    assertThat(telemetry.metric("eda.dlq.messages")).isPresent();
  }

  static List<String> names(ProducerRecord<?, ?> r) {
    List<String> out = new ArrayList<>();
    for (Header h : r.headers()) {
      out.add(h.key());
    }
    return out;
  }

  static String header(ProducerRecord<?, ?> r, String name) {
    return new String(r.headers().lastHeader(name).value(), StandardCharsets.UTF_8);
  }
}
