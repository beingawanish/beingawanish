package com.edacommerce.order.domain;

/** A compensation the CANCELLING state waits for (architecture §5.3 rule 6). */
public enum Compensation {
  RELEASE_RESERVATION,
  VOID_PAYMENT,
  CANCEL_FULFILMENT
}
