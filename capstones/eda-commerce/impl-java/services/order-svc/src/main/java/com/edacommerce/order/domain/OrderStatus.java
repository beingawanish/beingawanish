package com.edacommerce.order.domain;

/**
 * Customer-facing status (orders.yaml OrderStatus): coarser than the saga state and honest about
 * what is true; CONFIRMED is not "paid" (architecture §9, semantic lock).
 */
public enum OrderStatus {
  PENDING,
  CONFIRMED,
  CANCELLED,
  SHIPPED,
  DELIVERED,
  RETURN_IN_PROGRESS,
  RETURNED,
  PARTIALLY_RETURNED,
  NEEDS_ATTENTION;

  public static OrderStatus of(OrderSagaState state) {
    return switch (state) {
      case RESERVING_STOCK, AUTHORIZING_PAYMENT, COMMITTING_STOCK, CANCELLING -> PENDING;
      case AWAITING_FULFILMENT_ACK, FULFILLING, PACKED, CAPTURING -> CONFIRMED;
      case SHIPPED -> SHIPPED;
      case DELIVERED -> DELIVERED;
      case CANCELLED -> CANCELLED;
      case NEEDS_ATTENTION -> NEEDS_ATTENTION;
    };
  }
}
