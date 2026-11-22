package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.testing.RequiresPostgres;
import com.edacommerce.edacommon.webhooks.WebhookReceiver;
import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

@RequiresPostgres
class WebhookReceiverIT {
  final DbFixture db = new DbFixture();

  @AfterEach
  void close() {
    db.close();
  }

  @Test
  void duplicatesAreAcknowledgedAndStoredOnce() {
    WebhookVerifier verifier = new WebhookVerifier("s", Clock.systemUTC());
    WebhookReceiver receiver = new WebhookReceiver("psp", verifier, db.inbox, db.tx, db.metrics);
    byte[] body = "{\"pspEventId\":\"e9\"}".getBytes(StandardCharsets.UTF_8);
    long ts = System.currentTimeMillis() / 1000;
    assertThat(receiver.authentic(Long.toString(ts), verifier.sign(ts, body), body)).isTrue();
    assertThat(receiver.authentic(Long.toString(ts), "bad", body)).isFalse();
    WebhookReceiver.Store store = (id, raw) -> db.jdbc.update("INSERT INTO effect (id, n) VALUES (?, 1)", id);
    for (int i = 0; i < 3; i++) {
      WebhookReceiver.Result r = receiver.receive("e9", "authorization.succeeded", body, store);
      assertThat(r).isEqualTo(i == 0 ? WebhookReceiver.Result.ACCEPTED : WebhookReceiver.Result.DUPLICATE);
      assertThat(r.status().value()).isEqualTo(200);
    }
    assertThat(db.count("SELECT count(*) FROM effect")).isEqualTo(1);
    assertThat(db.count("SELECT count(*) FROM inbox WHERE consumer = 'psp-webhook'")).isEqualTo(1);
  }
}
