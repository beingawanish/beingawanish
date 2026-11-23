package com.edacommerce.fulfilment.domain;

/** A rule of the fulfilment domain was violated (mapped to NonRetryable by messaging adapters). */
public class FulfilmentException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public FulfilmentException(String message) {
    super(message);
  }
}
