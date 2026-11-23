package com.edacommerce.returns.domain;

/** A line being returned, priced from the order. */
public record ReturnItem(String lineId, String sku, int quantity, long unitPriceMinor) {
  public ReturnItem {
    if (quantity <= 0) {
      throw new ReturnsException("quantity must be positive for line " + lineId);
    }
  }

  public long valueMinor() {
    return unitPriceMinor * quantity;
  }
}
