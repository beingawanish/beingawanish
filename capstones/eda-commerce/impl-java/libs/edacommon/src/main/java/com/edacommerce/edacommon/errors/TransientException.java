package com.edacommerce.edacommon.errors;

/** A failure expected to clear within seconds. The consumer runtime retries it in place. */
public class TransientException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public TransientException(String message) {
    super(message);
  }

  public TransientException(String message, Throwable cause) {
    super(message, cause);
  }
}
