package com.edacommerce.payment.adapters.in.http;

import com.edacommerce.edacommon.webhooks.WebhookReceiver;
import com.edacommerce.payment.adapters.out.persistence.JdbcPspNotifications;
import com.edacommerce.payment.adapters.out.psp.PspWebhookPayload;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /webhooks/psp} (webhooks.yaml): verify HMAC over the raw body, dedupe on pspEventId
 * in the inbox, store, answer 200. The payment is updated afterwards by the notification processor
 * job.
 */
@RestController
public class PspWebhookController {
  private final WebhookReceiver receiver;
  private final JdbcPspNotifications store;
  private final ObjectMapper json;
  private final Runnable kick;

  public PspWebhookController(
      WebhookReceiver receiver,
      JdbcPspNotifications store,
      ObjectMapper json,
      Runnable pspNotificationKick) {
    this.receiver = receiver;
    this.store = store;
    this.json = json;
    this.kick = pspNotificationKick;
  }

  @PostMapping("/webhooks/psp")
  public ResponseEntity<Void> receive(
      @RequestHeader(name = "X-Webhook-Timestamp", required = false) String timestamp,
      @RequestHeader(name = "X-Psp-Signature", required = false) String signature,
      @RequestBody(required = false) byte[] body) {
    byte[] raw = body == null ? new byte[0] : body;
    if (!receiver.authentic(timestamp, signature, raw)) {
      return ResponseEntity.status(401).build();
    }
    PspWebhookPayload payload;
    try {
      payload = json.readValue(raw, PspWebhookPayload.class);
    } catch (IOException e) {
      return ResponseEntity.badRequest().build();
    }
    if (payload.pspEventId() == null
        || payload.eventType() == null
        || payload.merchantReference() == null) {
      return ResponseEntity.badRequest().build();
    }
    WebhookReceiver.Result result =
        receiver.receive(
            payload.pspEventId(),
            payload.eventType(),
            raw,
            (id, bytes) ->
                store.store(
                    id,
                    payload.eventType(),
                    payload.merchantReference(),
                    payload.pspPaymentId(),
                    payload.failureCode(),
                    bytes));
    if (result == WebhookReceiver.Result.ACCEPTED) {
      kick.run();
    }
    return ResponseEntity.status(result.status()).build();
  }
}
