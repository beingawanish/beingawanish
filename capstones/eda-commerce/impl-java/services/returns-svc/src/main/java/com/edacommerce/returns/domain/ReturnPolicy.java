package com.edacommerce.returns.domain;

import java.time.Duration;
import java.util.List;

/**
 * Configured rules of the returns saga (RETURN_AUTO_APPROVE_LIMIT_MINOR, RETURN_PARCEL_DUE_DAYS)
 * and the fixed retry schedule of architecture §6.4.
 */
public record ReturnPolicy(long autoApproveLimitMinor, Duration parcelDue) {
  /** Waits before resending a refund after a retryable failure: 1 min, 10 min, 1 h. */
  public static final List<Duration> REFUND_BACKOFF =
      List.of(Duration.ofMinutes(1), Duration.ofMinutes(10), Duration.ofHours(1));

  /** How long SETTLING waits for a reply before resending what is outstanding. */
  public static final Duration SETTLE_REPLY_TIMEOUT = Duration.ofMinutes(10);

  public static ReturnPolicy defaults() {
    return new ReturnPolicy(50_000, Duration.ofDays(14));
  }
}
