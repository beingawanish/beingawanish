package com.edacommerce.returns.domain;

/** A rule of the returns domain was violated. */
public class ReturnsException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public ReturnsException(String message) {
    super(message);
  }
}
