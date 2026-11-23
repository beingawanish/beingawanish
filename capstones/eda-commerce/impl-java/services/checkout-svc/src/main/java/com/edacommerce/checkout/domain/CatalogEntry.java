package com.edacommerce.checkout.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;

/**
 * One SKU in checkout's catalog read model, assembled from three compacted topics (ADR-0010). Any
 * part may be missing while the projection catches up.
 */
public record CatalogEntry(
    String sku,
    String name,
    boolean active,
    Money listPrice,
    Money salePrice,
    Integer available,
    Instant updatedAt) {

  /** What the customer pays per unit: the sale price when there is one. */
  public Money unitPrice() {
    return salePrice != null ? salePrice : listPrice;
  }

  public boolean sellable() {
    return active && name != null && listPrice != null;
  }

  public String availability() {
    if (available == null) {
      return "UNKNOWN";
    }
    if (available <= 0) {
      return "OUT_OF_STOCK";
    }
    return available <= 5 ? "LOW_STOCK" : "IN_STOCK";
  }
}
