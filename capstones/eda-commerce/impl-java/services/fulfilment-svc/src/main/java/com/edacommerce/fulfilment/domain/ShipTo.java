package com.edacommerce.fulfilment.domain;

/** Delivery address. Personal data: passed through to shipping, never logged (ADR-0013). */
public record ShipTo(
    String recipientName,
    String line1,
    String line2,
    String city,
    String region,
    String postalCode,
    String countryCode,
    String phone) {

  @Override
  public String toString() {
    return "ShipTo[redacted]";
  }
}
