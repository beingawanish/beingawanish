package com.edacommerce.catalog.domain;

/** An invalid product. */
public class CatalogException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public CatalogException(String message) {
    super(message);
  }
}
