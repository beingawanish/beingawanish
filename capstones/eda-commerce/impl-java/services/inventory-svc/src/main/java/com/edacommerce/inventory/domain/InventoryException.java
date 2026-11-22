package com.edacommerce.inventory.domain;

/** A command that can never succeed as sent (invariant violation). Not retryable. */
public class InventoryException extends RuntimeException {
  private static final long serialVersionUID = 1L;

  public InventoryException(String message) {
    super(message);
  }
}
