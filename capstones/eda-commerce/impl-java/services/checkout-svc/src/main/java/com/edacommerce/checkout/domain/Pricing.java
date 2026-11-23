package com.edacommerce.checkout.domain;

import com.edacommerce.kernel.Money;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Prices a cart from the read model. Prices are tax-inclusive (EU); the included VAT is computed
 * per line with banker's rounding and summed (guide §6.2). Shipping: STANDARD 4.99 (free from
 * 50.00), EXPRESS 9.99. These are this template's business rules, not contract.
 */
public final class Pricing {
  private Pricing() {}

  public static final BigDecimal VAT = new BigDecimal("0.19");
  public static final long FREE_SHIPPING_FROM_MINOR = 5000;

  /** A priced line. */
  public record Line(
      String lineId,
      String sku,
      String productName,
      int quantity,
      Money unitPrice,
      Money lineTotal,
      String availability) {}

  /** A priced cart. {@code pricedAt}: freshness of the oldest read-model row used. */
  public record Priced(
      List<Line> lines,
      Money subtotal,
      Money shippingFee,
      Money tax,
      Money total,
      Instant pricedAt,
      List<String> unsellable) {}

  public static Priced price(
      Cart cart, Map<String, CatalogEntry> catalog, String shippingMethod, Instant now) {
    List<Line> lines = new ArrayList<>();
    List<String> unsellable = new ArrayList<>();
    Money subtotal = Money.zero(cart.currency());
    Money tax = Money.zero(cart.currency());
    Instant pricedAt = now;
    int n = 0;
    for (Map.Entry<String, Integer> e : new TreeMap<>(cart.lines()).entrySet()) {
      CatalogEntry c = catalog.get(e.getKey());
      if (c == null || !c.sellable() || !c.unitPrice().currency().equals(cart.currency())) {
        unsellable.add(e.getKey());
        continue;
      }
      Money lineTotal = c.unitPrice().times(e.getValue());
      n++;
      lines.add(
          new Line(
              "L" + n,
              c.sku(),
              c.name(),
              e.getValue(),
              c.unitPrice(),
              lineTotal,
              c.availability()));
      subtotal = subtotal.plus(lineTotal);
      tax = tax.plus(lineTotal.includedTax(VAT));
      if (c.updatedAt() != null && c.updatedAt().isBefore(pricedAt)) {
        pricedAt = c.updatedAt();
      }
    }
    Money shipping = shippingFee(shippingMethod, subtotal);
    tax = tax.plus(shipping.includedTax(VAT));
    return new Priced(
        List.copyOf(lines),
        subtotal,
        shipping,
        tax,
        subtotal.plus(shipping),
        pricedAt,
        List.copyOf(unsellable));
  }

  static Money shippingFee(String method, Money subtotal) {
    if (method == null || subtotal.amountMinor() == 0) {
      return Money.zero(subtotal.currency());
    }
    if ("EXPRESS".equals(method)) {
      return Money.of(999, subtotal.currency());
    }
    return subtotal.amountMinor() >= FREE_SHIPPING_FROM_MINOR
        ? Money.zero(subtotal.currency())
        : Money.of(499, subtotal.currency());
  }
}
