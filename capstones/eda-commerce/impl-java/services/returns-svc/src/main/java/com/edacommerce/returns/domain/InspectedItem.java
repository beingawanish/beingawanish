package com.edacommerce.returns.domain;

/** Units of one line with one inspection outcome (ReturnInspected.results). */
public record InspectedItem(String lineId, String sku, int quantity, InspectionOutcome outcome) {}
