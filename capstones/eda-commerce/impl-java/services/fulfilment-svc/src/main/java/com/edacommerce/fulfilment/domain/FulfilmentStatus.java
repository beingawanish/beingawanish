package com.edacommerce.fulfilment.domain;

/** Lifecycle of an outbound warehouse order (one per fulfilmentId). */
public enum FulfilmentStatus {
  REQUESTED,
  ACCEPTED,
  PICKED,
  PACKED,
  DISPATCHED,
  CANCELLED,
  FAILED;

  /** The warehouse has acknowledged the order: a resent request re-answers FulfilmentAccepted. */
  public boolean acknowledged() {
    return this == ACCEPTED || this == PICKED || this == PACKED || this == DISPATCHED;
  }
}
