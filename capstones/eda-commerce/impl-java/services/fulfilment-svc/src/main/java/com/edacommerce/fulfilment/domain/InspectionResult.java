package com.edacommerce.fulfilment.domain;

/** Inspection of some units of one line, all with the same outcome. */
public record InspectionResult(
    String lineId, String sku, int quantity, InspectionOutcome outcome, String note) {}
