package com.edacommerce.order.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.List;

/**
 * The order as accepted at checkout (the write model). Lines and prices are frozen; the ship-to
 * address and email are personal data kept only because fulfilment needs them (ADR-0013).
 */
public record Order(
    String orderId,
    String checkoutId,
    String customerId,
    List<OrderLine> lines,
    Money subtotal,
    Money shippingFee,
    Money tax,
    Money total,
    PostalAddress shippingAddress,
    String contactEmail,
    String shippingMethod,
    String paymentMethodToken,
    Instant placedAt) {

  /** One frozen order line. */
  public record OrderLine(String lineId, String sku, String productName, int quantity, Money unitPrice, Money lineTotal) {}

  /** A postal address (personal data). */
  public record PostalAddress(
      String recipientName, String line1, String line2, String city, String region, String postalCode, String countryCode, String phone) {}

  public int itemCount() {
    return lines.stream().mapToInt(OrderLine::quantity).sum();
  }
}
