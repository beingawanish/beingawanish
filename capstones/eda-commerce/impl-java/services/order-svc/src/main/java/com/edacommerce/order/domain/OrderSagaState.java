package com.edacommerce.order.domain;

/** States of the order saga (architecture §5.1). Names are part of the contract (guide §1). */
public enum OrderSagaState {
  RESERVING_STOCK,
  AUTHORIZING_PAYMENT,
  COMMITTING_STOCK,
  AWAITING_FULFILMENT_ACK,
  FULFILLING,
  PACKED,
  CAPTURING,
  SHIPPED,
  DELIVERED,
  CANCELLING,
  CANCELLED,
  NEEDS_ATTENTION;

  public boolean isTerminal() {
    return this == DELIVERED || this == CANCELLED;
  }

  /** Before the pivot (OrderDispatched) every step is compensatable (ADR-0015). */
  public boolean beforeDispatch() {
    return switch (this) {
      case RESERVING_STOCK, AUTHORIZING_PAYMENT, COMMITTING_STOCK, AWAITING_FULFILMENT_ACK, FULFILLING, PACKED -> true;
      default -> false;
    };
  }
}
