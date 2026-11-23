package com.edacommerce.inventory.domain;

/** Lifecycle of a reservation (ADR-0016). REJECTED and RELEASED/EXPIRED are terminal. */
public enum ReservationStatus {
  HELD,
  COMMITTED,
  RELEASED,
  EXPIRED,
  REJECTED
}
