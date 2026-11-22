package com.edacommerce.edacommon.errors;

import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.http.HttpTimeoutException;
import java.sql.SQLTransientException;
import org.springframework.dao.ConcurrencyFailureException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.QueryTimeoutException;
import org.springframework.dao.RecoverableDataAccessException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.transaction.CannotCreateTransactionException;

/**
 * Classifies a failure once, walking the cause chain. Explicit edacommon exceptions win; known
 * infrastructure exceptions map to TRANSIENT; anything unknown is RETRY_LATER (ADR-0007: unknown
 * failures must neither block the partition nor be parked without a second chance).
 */
public final class ErrorClassifier {
  private ErrorClassifier() {}

  public static ErrorClass classify(Throwable error) {
    for (Throwable t = error; t != null; t = t.getCause() == t ? null : t.getCause()) {
      if (t instanceof NonRetryableException) {
        return ErrorClass.NON_RETRYABLE;
      }
      if (t instanceof RetryLaterException) {
        return ErrorClass.RETRY_LATER;
      }
      if (t instanceof TransientException) {
        return ErrorClass.TRANSIENT;
      }
    }
    for (Throwable t = error; t != null; t = t.getCause() == t ? null : t.getCause()) {
      if (t instanceof TransientDataAccessException
          || t instanceof RecoverableDataAccessException
          || t instanceof ConcurrencyFailureException
          || t instanceof QueryTimeoutException
          || t instanceof DataAccessResourceFailureException
          || t instanceof CannotCreateTransactionException
          || t instanceof SQLTransientException
          || t instanceof ConnectException
          || t instanceof SocketTimeoutException
          || t instanceof HttpTimeoutException) {
        return ErrorClass.TRANSIENT;
      }
      if (t instanceof DataIntegrityViolationException) {
        // A constraint violation is a bug or a contract breach; waiting will not change the data.
        return ErrorClass.NON_RETRYABLE;
      }
    }
    return ErrorClass.RETRY_LATER;
  }

  /** Re-throws {@code error} as exactly one of the three edacommon exception types. */
  public static RuntimeException normalise(Throwable error) {
    if (error instanceof TransientException
        || error instanceof RetryLaterException
        || error instanceof NonRetryableException) {
      return (RuntimeException) error;
    }
    String message = error.getClass().getSimpleName() + ": " + error.getMessage();
    return switch (classify(error)) {
      case TRANSIENT -> new TransientException(message, error);
      case RETRY_LATER -> new RetryLaterException(message, error);
      case NON_RETRYABLE -> new NonRetryableException(message, error);
    };
  }

  /** The most specific cause's simple class name; low-cardinality label for x-error-class and metrics. */
  public static String errorClassName(Throwable error) {
    Throwable t = error;
    while ((t instanceof TransientException
            || t instanceof RetryLaterException
            || t instanceof NonRetryableException)
        && t.getCause() != null) {
      t = t.getCause();
    }
    return t.getClass().getSimpleName();
  }
}
