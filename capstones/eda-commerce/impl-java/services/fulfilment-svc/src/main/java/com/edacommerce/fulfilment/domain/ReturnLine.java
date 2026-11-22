package com.edacommerce.fulfilment.domain;

/** A line the customer sends back. */
public record ReturnLine(String lineId, String sku, int quantity) {
  public ReturnLine {
    if (quantity <= 0) {
      throw new FulfilmentException("return quantity must be positive for line " + lineId);
    }
  }
}
