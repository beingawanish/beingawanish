package com.edacommerce.shipping.domain;

/** A rule of the shipping domain was violated (mapped to NonRetryable by messaging adapters). */
public class ShippingException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public ShippingException(String message) {
    super(message);
  }
}
