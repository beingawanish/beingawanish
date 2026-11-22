package com.edacommerce.shipping.adapters.in.http;

import com.edacommerce.edacommon.webhooks.WebhookReceiver;
import com.edacommerce.shipping.adapters.out.persistence.JdbcTrackingEvents;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.format.DateTimeParseException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/**
 * {@code POST /webhooks/carrier} (webhooks.yaml): verify the HMAC over the raw body, dedupe on
 * carrierEventId in the inbox, store the raw update, answer 200. The shipment is updated afterwards
 * by the tracking processor, in carrier-timestamp order.
 */
@RestController
public class CarrierWebhookController {

  /** webhooks.yaml CarrierTrackingEvent. */
  record Payload(
      String carrierEventId,
      String trackingNumber,
      String status,
      String exceptionCode,
      String location,
      String occurredAt) {}

  private final WebhookReceiver receiver;
  private final JdbcTrackingEvents store;
  private final ObjectMapper json;
  private final Runnable kick;

  public CarrierWebhookController(
      WebhookReceiver receiver,
      JdbcTrackingEvents store,
      ObjectMapper json,
      Runnable trackingKick) {
    this.receiver = receiver;
    this.store = store;
    this.json = json;
    this.kick = trackingKick;
  }

  @PostMapping("/webhooks/carrier")
  public ResponseEntity<Void> receive(
      @RequestHeader(name = "X-Webhook-Timestamp", required = false) String timestamp,
      @RequestHeader(name = "X-Carrier-Signature", required = false) String signature,
      @RequestBody(required = false) byte[] body) {
    byte[] raw = body == null ? new byte[0] : body;
    if (!receiver.authentic(timestamp, signature, raw)) {
      return ResponseEntity.status(401).build();
    }
    Payload p;
    Instant occurredAt;
    try {
      p = json.readValue(raw, Payload.class);
      if (p.carrierEventId() == null
          || p.trackingNumber() == null
          || p.status() == null
          || p.occurredAt() == null) {
        return ResponseEntity.badRequest().build();
      }
      occurredAt = OffsetDateTime.parse(p.occurredAt()).toInstant();
    } catch (IOException | DateTimeParseException e) {
      return ResponseEntity.badRequest().build();
    }
    WebhookReceiver.Result result =
        receiver.receive(
            p.carrierEventId(),
            "carrier." + p.status(),
            raw,
            (id, bytes) ->
                store.store(
                    id,
                    p.trackingNumber(),
                    p.status(),
                    p.exceptionCode(),
                    p.location(),
                    occurredAt,
                    bytes));
    if (result == WebhookReceiver.Result.ACCEPTED) {
      kick.run();
    }
    return ResponseEntity.status(result.status()).build();
  }
}
