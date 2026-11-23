package com.edacommerce.edacommon.envelope;

import com.edacommerce.common.Envelope;
import java.time.Instant;

/** What a handler knows about the message it is handling, besides its body. */
public record MessageContext(
    String eventId,
    String eventType,
    String topic,
    int partition,
    long offset,
    String key,
    String consumerGroup,
    Envelope envelope) {

  public String correlationId() {
    return envelope.getCorrelationId();
  }

  /** Causation for every message this handler emits: same flow, caused by this message. */
  public Causation causation() {
    return new Causation(envelope.getCorrelationId(), eventId);
  }

  public Instant occurredAt() {
    return envelope.getOccurredAt();
  }

  /** True for a command whose envelope.expiresAt has passed: the receiver must reject it. */
  public boolean isExpired(Instant now) {
    Instant expiresAt = envelope.getExpiresAt();
    return expiresAt != null && now.isAfter(expiresAt);
  }
}
