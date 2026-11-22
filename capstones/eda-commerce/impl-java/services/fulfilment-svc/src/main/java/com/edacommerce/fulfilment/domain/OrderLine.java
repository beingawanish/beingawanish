package com.edacommerce.fulfilment.domain;

/** A line to pick. */
public record OrderLine(String lineId, String sku, String productName, int quantity) {
  public OrderLine {
    if (quantity <= 0) {
      throw new FulfilmentException("quantity must be positive for line " + lineId);
    }
  }
}
