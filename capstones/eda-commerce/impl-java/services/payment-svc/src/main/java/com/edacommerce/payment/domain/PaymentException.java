package com.edacommerce.payment.domain;

/** A command that can never be applied as sent (for example voiding a captured payment). */
public class PaymentException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public PaymentException(String message) {
    super(message);
  }
}
