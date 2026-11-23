package com.edacommerce.edacommon.claimcheck;

/**
 * The claim check's object has passed its lifecycle expiry. A replayed old event hits this;
 * consumers skip with a warning rather than fail (ADR-0009).
 */
public class ClaimCheckExpiredException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public ClaimCheckExpiredException(String message) {
    super(message);
  }
}
