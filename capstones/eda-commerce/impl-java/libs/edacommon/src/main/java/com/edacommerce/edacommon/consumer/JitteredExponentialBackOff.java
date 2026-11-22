package com.edacommerce.edacommon.consumer;

import java.util.concurrent.ThreadLocalRandom;
import org.springframework.util.backoff.BackOff;
import org.springframework.util.backoff.BackOffExecution;

/**
 * In-place retry schedule of ADR-0007: exponential from 200 ms, capped at 3.2 s, with +/-20 %
 * jitter, {@code maxRetries} retries after the first attempt (default 4, i.e. 5 attempts).
 */
public class JitteredExponentialBackOff implements BackOff {
  private final long initialMs;
  private final long maxMs;
  private final int maxRetries;

  public JitteredExponentialBackOff(long initialMs, long maxMs, int maxRetries) {
    this.initialMs = initialMs;
    this.maxMs = maxMs;
    this.maxRetries = maxRetries;
  }

  public static JitteredExponentialBackOff adr0007() {
    return new JitteredExponentialBackOff(200, 3200, 4);
  }

  @Override
  public BackOffExecution start() {
    return new BackOffExecution() {
      private int attempt;

      @Override
      public long nextBackOff() {
        if (attempt >= maxRetries) {
          return STOP;
        }
        long base = Math.min(maxMs, initialMs << attempt);
        attempt++;
        double jitter = 0.8 + ThreadLocalRandom.current().nextDouble() * 0.4;
        return Math.max(1, Math.round(base * jitter));
      }
    };
  }
}
