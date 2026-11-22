package com.edacommerce.edacommon.envelope;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.common.Envelope;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.inventory.ReserveStock;
import java.time.Instant;
import org.junit.jupiter.api.Test;

class EnvelopesTest {
  @Test
  void buildsTheEnvelopeFromTheMessageAndItsCause() {
    ReserveStock cmd = GoldenFixtures.decode(ReserveStock.class);
    OutgoingMessage msg = OutgoingMessage.of("inventory.commands.v1", "o1", cmd, "Order", "o1", 3);
    Envelope env =
        Envelopes.build(
            "e2", msg, new Causation("o1", "e1"), "order-svc", Instant.EPOCH, "00-tp", null);
    assertThat(env.getType()).isEqualTo("com.edacommerce.inventory.ReserveStock");
    assertThat(env.getVersion()).isEqualTo(1);
    assertThat(env.getPartitionKey()).isEqualTo("o1");
    assertThat(env.getCausationId()).isEqualTo("e1");
    assertThat(env.getCorrelationId()).isEqualTo("o1");
    assertThat(env.getProducer()).isEqualTo("order-svc");
    assertThat(env.getAggregateVersion()).isEqualTo(3);
    assertThat(Envelopes.versionOfTopic("order.events.v12")).isEqualTo(12);
    Envelopes.set(cmd, env);
    assertThat(Envelopes.of(cmd)).isSameAs(env);
  }
}
