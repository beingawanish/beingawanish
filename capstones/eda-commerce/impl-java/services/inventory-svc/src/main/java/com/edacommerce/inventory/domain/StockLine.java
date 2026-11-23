package com.edacommerce.inventory.domain;

/** A SKU and a quantity (no prices). */
public record StockLine(String sku, int quantity) {
  public StockLine {
    if (sku == null || sku.isBlank()) {
      throw new InventoryException("sku is required");
    }
    if (quantity <= 0) {
      throw new InventoryException("quantity must be positive for " + sku);
    }
  }
}
