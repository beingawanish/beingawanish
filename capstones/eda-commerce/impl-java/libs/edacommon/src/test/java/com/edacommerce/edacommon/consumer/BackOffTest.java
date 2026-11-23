package com.edacommerce.edacommon.consumer;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import org.springframework.util.backoff.BackOffExecution;

class BackOffTest {
  @Test
  void fiveAttemptsExponentialFrom200msCappedAt3200msWithJitter() {
    BackOffExecution e = JitteredExponentialBackOff.adr0007().start();
    long[] base = {200, 400, 800, 1600};
    for (long b : base) {
      assertThat(e.nextBackOff()).isBetween((long) (b * 0.8) - 1, (long) (b * 1.2) + 1);
    }
    assertThat(e.nextBackOff()).isEqualTo(BackOffExecution.STOP);
  }
}
