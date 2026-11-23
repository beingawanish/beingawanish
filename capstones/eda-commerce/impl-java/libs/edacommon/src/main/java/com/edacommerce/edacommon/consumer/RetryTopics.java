package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.errors.ErrorClass;
import java.time.Duration;
import java.util.List;

/**
 * Per-consumer-group retry and dead-letter topics (ADR-0007, topics.yaml retryPolicy): {@code
 * G.retry.10s}, {@code G.retry.1m}, {@code G.retry.10m}, {@code G.dlq}.
 */
public final class RetryTopics {
  private RetryTopics() {}

  static final List<String> SUFFIXES = List.of("retry.10s", "retry.1m", "retry.10m");
  static final List<Duration> DELAYS =
      List.of(Duration.ofSeconds(10), Duration.ofMinutes(1), Duration.ofMinutes(10));

  /** Where a failed record goes next. {@code attempt} is the new value of x-retry-attempt. */
  public record Destination(String topic, int attempt, Duration delay, boolean deadLetter) {}

  public static List<String> retryTopics(String group) {
    return SUFFIXES.stream().map(s -> group + "." + s).toList();
  }

  public static String firstRetry(String group) {
    return group + "." + SUFFIXES.get(0);
  }

  public static String dlq(String group) {
    return group + ".dlq";
  }

  /**
   * The next hop: retry topics in order, then the DLQ; non-retryable failures go straight to the
   * DLQ. Transient failures reach this only after in-place retries are exhausted, and then behave
   * like RetryLater.
   *
   * @param previousAttempt x-retry-attempt of the failed record (0 if it came from a source topic)
   */
  public static Destination next(String group, int previousAttempt, ErrorClass errorClass) {
    int attempt = previousAttempt + 1;
    if (errorClass == ErrorClass.NON_RETRYABLE || attempt > SUFFIXES.size()) {
      return new Destination(dlq(group), attempt, Duration.ZERO, true);
    }
    return new Destination(
        group + "." + SUFFIXES.get(attempt - 1), attempt, DELAYS.get(attempt - 1), false);
  }
}
