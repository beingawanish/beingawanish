package com.edacommerce.returns.domain;

/** Where the carrier collects the return. Personal data, never logged. */
public record Pickup(
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
    return "Pickup[redacted]";
  }
}
