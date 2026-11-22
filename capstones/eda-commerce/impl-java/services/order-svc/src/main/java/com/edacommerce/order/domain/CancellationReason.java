package com.edacommerce.order.domain;

/** Why an order was cancelled (mirrors the contract enum, minus UNKNOWN which we never emit). */
public enum CancellationReason {
  OUT_OF_STOCK,
  PAYMENT_DECLINED,
  RESERVATION_EXPIRED,
  FULFILMENT_FAILED,
  CUSTOMER_REQUESTED,
  SAGA_TIMEOUT
}
