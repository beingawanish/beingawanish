package com.edacommerce.catalog.domain;

/**
 * Advisory availability shown on product pages (catalog.yaml ProductView.availability). The
 * reservation in inventory-svc is the real check (ADR-0016).
 */
public enum Availability {
  IN_STOCK,
  LOW_STOCK,
  OUT_OF_STOCK,
  UNKNOWN;

  public static final int LOW_STOCK_THRESHOLD = 5;

  public static Availability of(Integer available) {
    if (available == null) {
      return UNKNOWN;
    }
    if (available <= 0) {
      return OUT_OF_STOCK;
    }
    return available <= LOW_STOCK_THRESHOLD ? LOW_STOCK : IN_STOCK;
  }
}
