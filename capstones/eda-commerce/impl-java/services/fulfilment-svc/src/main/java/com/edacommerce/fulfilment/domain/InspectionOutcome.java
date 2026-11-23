package com.edacommerce.fulfilment.domain;

/** Per-unit result of inspecting a returned item. */
public enum InspectionOutcome {
  RESTOCKABLE,
  DAMAGED,
  MISSING
}
