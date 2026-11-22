package com.edacommerce.order.domain;

import java.time.Duration;

/** Step deadlines of architecture §5.2 (SAGA_* variables, guide §7). */
public record SagaTimeouts(
    Duration stock,
    Duration payment,
    Duration commit,
    Duration fulfilmentAck,
    int fulfilmentMaxResends,
    Duration dispatch,
    Duration capture,
    Duration compensation) {

  public static final Duration SHIPPED_TIMEOUT = Duration.ofDays(30);
  public static final Duration CAPTURE_RETRY_BACKOFF = Duration.ofMinutes(1);
  public static final Duration RETURN_WINDOW = Duration.ofDays(30);
  /** Raise attention this long before an authorisation lapses if the parcel has not left (ADR-0015). */
  public static final Duration AUTHORIZATION_SAFETY = Duration.ofDays(2);
  public static final int RESERVE_RESENDS = 2;
  public static final int AUTHORIZE_RESENDS = 1;
  public static final int MAX_CAPTURE_RETRIES = 5;
  public static final int COMPENSATION_ALERT_AFTER = 10;
  public static final int RESERVATION_TTL_SECONDS = 900;

  public static SagaTimeouts defaults() {
    return new SagaTimeouts(Duration.ofSeconds(30), Duration.ofSeconds(180), Duration.ofSeconds(30),
        Duration.ofSeconds(600), 3, Duration.ofHours(24), Duration.ofSeconds(300), Duration.ofSeconds(60));
  }
}
