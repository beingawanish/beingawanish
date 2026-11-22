package com.edacommerce.edacommon.logging;

import org.slf4j.MDC;
import org.springframework.lang.Nullable;

/**
 * MDC keys for the JSON log fields of guide §6.4. {@code trace_id} and {@code span_id} are filled by
 * the OpenTelemetry logback MDC instrumentation; the message fields are set here by the consumer
 * runtime and cleared when the record is done.
 */
public final class LogFields {
  private LogFields() {}

  public static final String CORRELATION_ID = "correlation_id";
  public static final String EVENT_ID = "event_id";
  public static final String EVENT_TYPE = "event_type";
  public static final String ORDER_ID = "order_id";
  public static final String RETURN_ID = "return_id";

  /** Message-scoped MDC entries; closing the scope removes them. */
  public static final class Scope implements AutoCloseable {
    private Scope() {}

    public Scope correlation(@Nullable String correlationId, @Nullable String orderId) {
      put(CORRELATION_ID, correlationId);
      put(ORDER_ID, orderId);
      return this;
    }

    @Override
    public void close() {
      MDC.remove(CORRELATION_ID);
      MDC.remove(EVENT_ID);
      MDC.remove(EVENT_TYPE);
      MDC.remove(ORDER_ID);
      MDC.remove(RETURN_ID);
    }
  }

  public static Scope forMessage(String eventId, String eventType) {
    Scope scope = new Scope();
    put(EVENT_ID, eventId);
    put(EVENT_TYPE, eventType);
    return scope;
  }

  public static void put(String key, @Nullable String value) {
    if (value != null) {
      MDC.put(key, value);
    }
  }
}
