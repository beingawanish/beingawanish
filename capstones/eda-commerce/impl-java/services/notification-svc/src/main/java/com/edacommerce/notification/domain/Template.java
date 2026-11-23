package com.edacommerce.notification.domain;

/** The customer messages this shop sends; {@link #id} is NotificationSent.template. */
public enum Template {
  ORDER_CONFIRMED("order-confirmed"),
  ORDER_CANCELLED("order-cancelled"),
  ORDER_SHIPPED("order-shipped"),
  INVOICE("invoice"),
  ORDER_DELIVERED("order-delivered"),
  SHIPMENT_PROBLEM("shipment-problem"),
  RETURN_AUTHORIZED("return-authorized"),
  RETURN_LABEL("return-label"),
  RETURN_REJECTED("return-rejected"),
  RETURN_REFUNDED("return-refunded"),
  RETURN_EXPIRED("return-expired");

  private final String id;

  Template(String id) {
    this.id = id;
  }

  public String id() {
    return id;
  }
}
