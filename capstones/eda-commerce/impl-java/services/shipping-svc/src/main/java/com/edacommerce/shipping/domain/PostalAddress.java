package com.edacommerce.shipping.domain;

/** A pickup or delivery address. Personal data: printed on the label, never logged. */
public record PostalAddress(
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
    return "PostalAddress[redacted]";
  }
}
