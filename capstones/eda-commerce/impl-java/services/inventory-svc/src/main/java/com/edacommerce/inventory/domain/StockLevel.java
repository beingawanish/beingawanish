package com.edacommerce.inventory.domain;

/** One stock row: what is published on inventory.stock-level.v1. */
public record StockLevel(String sku, int onHand, int reserved, long version) {
  public int available() {
    return Math.max(0, onHand - reserved);
  }
}
