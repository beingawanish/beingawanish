package com.edacommerce.checkout.domain;

/** A cart or checkout rule violation; {@code code} becomes the problem type slug. */
public class CheckoutException extends RuntimeException {
  private static final long serialVersionUID = 1L;
  private final String code;

  public CheckoutException(String code, String message) {
    super(message);
    this.code = code;
  }

  public String code() {
    return code;
  }
}
