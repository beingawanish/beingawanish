package com.edacommerce.edacommon.errors;

/** A failure expected to clear within minutes. The record moves to the next retry topic. */
public class RetryLaterException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public RetryLaterException(String message) {
    super(message);
  }

  public RetryLaterException(String message, Throwable cause) {
    super(message, cause);
  }
}
