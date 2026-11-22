package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.outbox.PollingOutboxRelay;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.KeepOpenMockProducer;
import com.edacommerce.edacommon.testing.RequiresPostgres;
import com.edacommerce.order.OrderPlaced;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.Header;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.mock.MockProducerFactory;

/** Checklist: polling relay publishes in order with headers identical to the Debezium configuration. */
@RequiresPostgres
class PollingOutboxRelayIT {
  final DbFixture db = new DbFixture();
  final KeepOpenMockProducer producer = KeepOpenMockProducer.create();
  final PollingOutboxRelay relay =
      new PollingOutboxRelay(db.jdbc, db.tx, new KafkaTemplate<>(new MockProducerFactory<>(() -> producer)), db.metrics, 100);

  @AfterEach
  void close() {
    db.close();
  }

  @Test
  void publishesInInsertionOrderWithDebeziumHeadersAndMarksRows() {
    List<String> ids = new ArrayList<>();
    for (int i = 0; i < 5; i++) {
      OrderPlaced e = GoldenFixtures.decode(OrderPlaced.class);
      String key = "order-" + (i % 2);
      ids.add(
          db.tx.execute(
              s -> db.outbox.append(OutgoingMessage.of("order.events.v1", key, e, "Order", key, 1), Causation.root(key))));
    }

    assertThat(relay.relayOnce()).isEqualTo(5);
    assertThat(relay.relayOnce()).isZero();

    List<ProducerRecord<String, byte[]>> sent = producer.history();
    assertThat(sent).extracting(r -> header(r, "ce_id")).containsExactlyElementsOf(ids);
    ProducerRecord<String, byte[]> first = sent.get(0);
    assertThat(first.topic()).isEqualTo("order.events.v1");
    assertThat(first.key()).isEqualTo("order-0");
    assertThat(first.value()[0]).isZero();
    List<String> names = new ArrayList<>();
    for (Header h : first.headers()) {
      names.add(h.key());
    }
    assertThat(names)
        .containsExactly(
            "id", "ce_id", "ce_type", "ce_source", "ce_time", "correlation_id", "causation_id",
            "traceparent", "tracestate", "ce_specversion");
    assertThat(header(first, "id")).isEqualTo(ids.get(0));
    assertThat(header(first, "ce_type")).isEqualTo("com.edacommerce.order.OrderPlaced");
    assertThat(header(first, "ce_source")).isEqualTo("test-svc");
    assertThat(header(first, "ce_specversion")).isEqualTo("1.0");
    assertThat(header(first, "ce_time")).matches("\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\d(\\.\\d+)?Z");
    assertThat(first.headers().lastHeader("causation_id").value()).isNull();
    assertThat(db.count("SELECT count(*) FROM outbox WHERE published_at IS NULL")).isZero();
    assertThat(db.telemetry.metric("eda.outbox.pending")).isPresent();
  }

  static String header(ProducerRecord<String, byte[]> r, String name) {
    byte[] v = r.headers().lastHeader(name).value();
    return v == null ? null : new String(v, StandardCharsets.UTF_8);
  }
}
