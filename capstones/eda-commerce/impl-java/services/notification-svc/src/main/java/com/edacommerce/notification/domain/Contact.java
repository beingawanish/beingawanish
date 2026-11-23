package com.edacommerce.notification.domain;

import java.time.Duration;
import java.time.Instant;

/**
 * How to reach the customer of one order, learnt from OrderPlaced. Personal data: kept only here,
 * only until {@code retainUntil} (ADR-0013), never logged.
 */
public record Contact(
    String orderId, String customerId, String email, String name, Instant retainUntil) {

  public static Contact fromOrder(
      String orderId,
      String customerId,
      String email,
      String name,
      Instant placedAt,
      Duration retention) {
    if (email == null || email.isBlank()) {
      throw new NotificationException("order " + orderId + " has no contact email");
    }
    return new Contact(orderId, customerId, email, name, placedAt.plus(retention));
  }

  @Override
  public String toString() {
    return "Contact[orderId=" + orderId + ", customerId=" + customerId + ", redacted]";
  }
}
