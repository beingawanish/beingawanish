package com.edacommerce.checkout.domain;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * A shopping cart: quantities per SKU, versioned for If-Match (ADR-0012). Prices are never stored.
 */
public record Cart(
    String cartId,
    String customerId,
    String currency,
    Status status,
    Map<String, Integer> lines,
    long version) {

  public enum Status {
    OPEN,
    CHECKED_OUT,
    ABANDONED
  }

  public Cart {
    lines = Map.copyOf(lines);
  }

  public static Cart open(String cartId, String customerId, String currency) {
    return new Cart(cartId, customerId, currency, Status.OPEN, Map.of(), 1);
  }

  /** PUT semantics: set the quantity (idempotent by nature). */
  public Cart setItem(CatalogEntry entry, int quantity) {
    requireOpen();
    if (quantity < 1 || quantity > 99) {
      throw new CheckoutException("invalid-quantity", "quantity must be between 1 and 99");
    }
    if (entry == null || !entry.sellable()) {
      throw new CheckoutException(
          entry == null ? "unknown-sku" : "discontinued-sku",
          "SKU cannot be sold: " + (entry == null ? "unknown" : entry.sku()));
    }
    if (!entry.unitPrice().currency().equals(currency)) {
      throw new CheckoutException(
          "currency-mismatch", "SKU " + entry.sku() + " is not priced in " + currency);
    }
    if (entry.available() != null && quantity > entry.available()) {
      throw new CheckoutException(
          "insufficient-availability",
          "only " + Math.max(0, entry.available()) + " of " + entry.sku() + " available");
    }
    Map<String, Integer> next = new LinkedHashMap<>(lines);
    next.put(entry.sku(), quantity);
    return new Cart(cartId, customerId, currency, status, next, version + 1);
  }

  public Cart removeItem(String sku) {
    requireOpen();
    Map<String, Integer> next = new LinkedHashMap<>(lines);
    next.remove(sku);
    return new Cart(cartId, customerId, currency, status, next, version + 1);
  }

  public Cart checkedOut() {
    requireOpen();
    return new Cart(cartId, customerId, currency, Status.CHECKED_OUT, lines, version + 1);
  }

  private void requireOpen() {
    if (status != Status.OPEN) {
      throw new CheckoutException("cart-not-open", "cart " + cartId + " is " + status);
    }
  }
}
