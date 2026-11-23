package com.edacommerce.fulfilment.domain;

/** Returns intake: expected (ExpectReturn), received (parcel delivered), inspected. */
public enum IntakeStatus {
  EXPECTED,
  RECEIVED,
  INSPECTED
}
