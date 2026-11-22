package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.RequiresPostgres;
import com.edacommerce.order.OrderPlaced;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

@RequiresPostgres
class OutboxWriterIT {
  final DbFixture db = new DbFixture();

  @AfterEach
  void close() {
    db.close();
  }

  OutgoingMessage placed() {
    OrderPlaced e = GoldenFixtures.decode(OrderPlaced.class);
    return OutgoingMessage.of("order.events.v1", e.getOrderId(), e, "Order", e.getOrderId(), 1);
  }

  @Test
  void appendsAWireFormatRowWithEnvelopeColumnsInTheCallersTransaction() {
    OutgoingMessage msg = placed();
    String id = db.tx.execute(s -> db.outbox.append(msg, new Causation("corr-1", "cause-1")));

    Map<String, Object> row = db.jdbc.queryForMap("SELECT * FROM outbox WHERE id = ?::uuid", id);
    assertThat(row.get("topic")).isEqualTo("order.events.v1");
    assertThat(row.get("aggregate_id")).isEqualTo(msg.key());
    assertThat(row.get("aggregate_type")).isEqualTo("Order");
    assertThat(row.get("event_type")).isEqualTo("com.edacommerce.order.OrderPlaced");
    assertThat(row.get("producer")).isEqualTo("test-svc");
    assertThat(row.get("correlation_id")).isEqualTo("corr-1");
    assertThat(row.get("causation_id")).isEqualTo("cause-1");
    assertThat(row.get("published_at")).isNull();
    byte[] payload = (byte[]) row.get("payload");
    assertThat(payload[0]).isZero();
    OrderPlaced back = db.serde.deserialize(payload, OrderPlaced.class);
    assertThat(back.getEnvelope().getEventId()).isEqualTo(id);
    assertThat(back.getEnvelope().getPartitionKey()).isEqualTo(msg.key());
    assertThat(back.getEnvelope().getCausationId()).isEqualTo("cause-1");
    assertThat(back.getEnvelope().getProducer()).isEqualTo("test-svc");
  }

  @Test
  void rollingBackPublishesNothing() {
    db.tx.executeWithoutResult(
        s -> {
          db.outbox.append(placed(), Causation.root("c"));
          s.setRollbackOnly();
        });
    assertThat(db.count("SELECT count(*) FROM outbox")).isZero();
  }

  @Test
  void refusesToWriteOutsideATransaction() {
    assertThatThrownBy(() -> db.outbox.append(placed(), Causation.root("c")))
        .isInstanceOf(IllegalStateException.class);
  }
}
