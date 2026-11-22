package com.edacommerce.returns.application;

/** POST /ops/returns/{id}/decision while the return is not waiting for that decision (409). */
public class NotWaitingForDecisionException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public NotWaitingForDecisionException(String message) {
    super(message);
  }
}
