package com.edacommerce.catalog.domain;

/** Product lifecycle (contract enum minus UNKNOWN, which is a reader default only). */
public enum ProductStatus {
  ACTIVE,
  DISCONTINUED
}
