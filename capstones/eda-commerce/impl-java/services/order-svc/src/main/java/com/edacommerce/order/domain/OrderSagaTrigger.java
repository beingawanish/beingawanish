package com.edacommerce.order.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;

/**
 * Everything that can move the order saga: replies from participants, choreographed events, the
 * deadline timer and the operator. Replies carry the business id they answer, so they are matched
 * by id and state, never by arrival order (architecture §5.3 rule 3).
 */
public sealed interface OrderSagaTrigger {
  record StockReserved(String reservationId) implements OrderSagaTrigger {}

  record StockReservationRejected(String reservationId) implements OrderSagaTrigger {}

  record ReservationCommitted(String reservationId) implements OrderSagaTrigger {}

  record ReservationReleased(String reservationId) implements OrderSagaTrigger {}

  record ReservationExpired(String reservationId) implements OrderSagaTrigger {}

  record PaymentAuthorized(String paymentId, Instant authorizationExpiresAt) implements OrderSagaTrigger {}

  record PaymentDeclined(String paymentId, String reason) implements OrderSagaTrigger {}

  record PaymentVoided(String paymentId) implements OrderSagaTrigger {}

  record PaymentCaptured(String paymentId, Money amount) implements OrderSagaTrigger {}

  record PaymentCaptureFailed(String paymentId, String reason, boolean retryable) implements OrderSagaTrigger {}

  record FulfilmentAccepted(String fulfilmentId) implements OrderSagaTrigger {}

  record OrderPacked(String fulfilmentId) implements OrderSagaTrigger {}

  record OrderDispatched(String fulfilmentId, String shipmentId) implements OrderSagaTrigger {}

  record FulfilmentFailed(String fulfilmentId, String reason) implements OrderSagaTrigger {}

  record FulfilmentCancelled(String fulfilmentId) implements OrderSagaTrigger {}

  record ShipmentCreated(String shipmentId, boolean outbound, String carrier, String trackingNumber) implements OrderSagaTrigger {}

  record ShipmentDelivered(String shipmentId, boolean outbound, Instant deliveredAt) implements OrderSagaTrigger {}

  record ShipmentException(String shipmentId, boolean outbound, boolean lost, String code) implements OrderSagaTrigger {}

  record Deadline() implements OrderSagaTrigger {}

  record OperatorRetry() implements OrderSagaTrigger {}
}
