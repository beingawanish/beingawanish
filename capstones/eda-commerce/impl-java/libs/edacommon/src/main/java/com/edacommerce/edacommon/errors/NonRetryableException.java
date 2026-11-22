package com.edacommerce.edacommon.errors;

/**
 * A failure waiting cannot fix (poison message, invariant violation). The record goes to the DLQ.
 */
public class NonRetryableException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public NonRetryableException(String message) {
    super(message);
  }

  public NonRetryableException(String message, Throwable cause) {
    super(message, cause);
  }
}
