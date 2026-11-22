package com.edacommerce.returns.domain;

/** How a return closed (ReturnClosed.outcome; also the eda.saga.outcomes value). */
public enum ReturnOutcome {
  REFUNDED,
  PARTIALLY_REFUNDED,
  REJECTED,
  EXPIRED,
  MANUAL_REVIEW
}
