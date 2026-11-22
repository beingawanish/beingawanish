package com.edacommerce.order.domain;

/** Commands the saga sends (the application adds order details when mapping to messages). */
public sealed interface OrderSagaCommand {
  record ReserveStock(String reservationId, int ttlSeconds) implements OrderSagaCommand {}

  record CommitReservation(String reservationId) implements OrderSagaCommand {}

  record ReleaseReservation(String reservationId, String reason) implements OrderSagaCommand {}

  record AuthorizePayment(String paymentId) implements OrderSagaCommand {}

  record VoidPayment(String paymentId, String reason) implements OrderSagaCommand {}

  record CapturePayment(String paymentId) implements OrderSagaCommand {}

  record RequestFulfilment(String fulfilmentId, int attempt) implements OrderSagaCommand {}

  record CancelFulfilment(String fulfilmentId, String reason) implements OrderSagaCommand {}
}
