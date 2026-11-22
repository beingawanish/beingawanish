package com.edacommerce.edacommon.consumer;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.errors.ErrorClass;
import java.time.Duration;
import org.junit.jupiter.api.Test;

class RetryTopicsTest {

  @Test
  void topicNamesFollowAdr0007() {
    assertThat(RetryTopics.retryTopics("payment-svc"))
        .containsExactly("payment-svc.retry.10s", "payment-svc.retry.1m", "payment-svc.retry.10m");
    assertThat(RetryTopics.dlq("payment-svc")).isEqualTo("payment-svc.dlq");
  }

  @Test
  void retryLaterWalksTheLadderThenTheDlq() {
    assertThat(RetryTopics.next("g", 0, ErrorClass.RETRY_LATER))
        .isEqualTo(new RetryTopics.Destination("g.retry.10s", 1, Duration.ofSeconds(10), false));
    assertThat(RetryTopics.next("g", 1, ErrorClass.RETRY_LATER).topic()).isEqualTo("g.retry.1m");
    assertThat(RetryTopics.next("g", 2, ErrorClass.TRANSIENT).topic()).isEqualTo("g.retry.10m");
    assertThat(RetryTopics.next("g", 3, ErrorClass.RETRY_LATER))
        .isEqualTo(new RetryTopics.Destination("g.dlq", 4, Duration.ZERO, true));
  }

  @Test
  void nonRetryableGoesStraightToTheDlq() {
    assertThat(RetryTopics.next("g", 0, ErrorClass.NON_RETRYABLE).topic()).isEqualTo("g.dlq");
  }
}
