package com.edacommerce.returns.domain;

/** States of the returns saga (architecture §6.1). Names are part of the contract (guide §1). */
public enum ReturnSagaState {
  REQUESTED,
  MANUAL_REVIEW,
  AUTHORIZED,
  AWAITING_PARCEL,
  AWAITING_INSPECTION,
  SETTLING,
  REFUND_REVIEW,
  REJECTED,
  EXPIRED,
  CLOSED;

  /**
   * States the saga passes through within one trigger: their outgoing transition needs no outside
   * input (AUTHORIZED sends the label commands, REJECTED and EXPIRED close).
   */
  public boolean transient_() {
    return this == AUTHORIZED || this == REJECTED || this == EXPIRED;
  }

  /** Human-owned states (counted as MANUAL_REVIEW, guide §8). */
  public boolean attention() {
    return this == MANUAL_REVIEW || this == REFUND_REVIEW;
  }
}
