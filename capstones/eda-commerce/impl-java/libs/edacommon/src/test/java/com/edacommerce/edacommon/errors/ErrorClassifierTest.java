package com.edacommerce.edacommon.errors;

import static org.assertj.core.api.Assertions.assertThat;

import java.net.ConnectException;
import org.junit.jupiter.api.Test;
import org.springframework.dao.CannotAcquireLockException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.OptimisticLockingFailureException;

class ErrorClassifierTest {
  @Test
  void explicitTypesWinAnywhereInTheCauseChain() {
    assertThat(ErrorClassifier.classify(new IllegalStateException(new NonRetryableException("x"))))
        .isEqualTo(ErrorClass.NON_RETRYABLE);
    assertThat(ErrorClassifier.classify(new RetryLaterException("x")))
        .isEqualTo(ErrorClass.RETRY_LATER);
  }

  @Test
  void infrastructureFailuresAreTransient() {
    assertThat(ErrorClassifier.classify(new CannotAcquireLockException("deadlock")))
        .isEqualTo(ErrorClass.TRANSIENT);
    assertThat(ErrorClassifier.classify(new OptimisticLockingFailureException("v")))
        .isEqualTo(ErrorClass.TRANSIENT);
    assertThat(ErrorClassifier.classify(new RuntimeException(new ConnectException("refused"))))
        .isEqualTo(ErrorClass.TRANSIENT);
  }

  @Test
  void constraintViolationsAreNonRetryableAndUnknownIsRetryLater() {
    assertThat(ErrorClassifier.classify(new DataIntegrityViolationException("dup")))
        .isEqualTo(ErrorClass.NON_RETRYABLE);
    assertThat(ErrorClassifier.classify(new IllegalArgumentException("?")))
        .isEqualTo(ErrorClass.RETRY_LATER);
    assertThat(ErrorClassifier.normalise(new IllegalArgumentException("?")))
        .isInstanceOf(RetryLaterException.class);
    assertThat(
            ErrorClassifier.errorClassName(
                new RetryLaterException("x", new java.io.IOException("y"))))
        .isEqualTo("IOException");
  }
}
