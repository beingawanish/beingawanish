package com.edacommerce.returns.domain;

/** POST /returns is refused (returns.yaml 422). */
public class IneligibleReturnException extends ReturnsException {
  private static final long serialVersionUID = 1L;

  /** Why. */
  public enum Reason {
    NOT_DELIVERED,
    WINDOW_CLOSED,
    QUANTITY_EXCEEDED,
    UNKNOWN_LINE
  }

  private final Reason reason;

  public IneligibleReturnException(Reason reason, String message) {
    super(message);
    this.reason = reason;
  }

  public Reason reason() {
    return reason;
  }
}
