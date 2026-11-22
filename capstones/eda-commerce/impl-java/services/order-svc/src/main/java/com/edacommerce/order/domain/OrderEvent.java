package com.edacommerce.order.domain;

import java.time.Instant;

/**
 * Facts on order.events.v1. Each carries the order's aggregate version, strictly increasing per
 * order (topics.yaml), which read models use to drop stale updates.
 */
public sealed interface OrderEvent {
  long version();

  record Placed(long version) implements OrderEvent {}

  record Confirmed(long version) implements OrderEvent {}

  record Cancelled(long version, CancellationReason reason, String detail, boolean paymentVoided) implements OrderEvent {}

  record Shipped(long version) implements OrderEvent {}

  /** The application renders and stores the invoice, then publishes InvoiceIssued (claim check). */
  record InvoiceToIssue(long version, String invoiceId) implements OrderEvent {}

  record Delivered(long version, Instant deliveredAt, Instant returnWindowEndsAt) implements OrderEvent {}

  record RequiresAttention(long version, OrderSagaState state, String issue) implements OrderEvent {}
}
