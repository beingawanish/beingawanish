package com.edacommerce.edacommon.envelope;

import java.util.Objects;
import org.springframework.lang.Nullable;

/**
 * Where an outgoing message comes from: the business flow it belongs to and the message that caused
 * it. {@code causationId} is null only for messages started by an HTTP request or a timer.
 */
public record Causation(String correlationId, @Nullable String causationId) {
  public Causation {
    Objects.requireNonNull(correlationId, "correlationId");
  }

  /** A new flow started by an HTTP request or a timer. */
  public static Causation root(String correlationId) {
    return new Causation(correlationId, null);
  }
}
