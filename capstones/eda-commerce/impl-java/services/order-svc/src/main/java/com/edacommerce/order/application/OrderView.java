package com.edacommerce.order.application;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.OrderStatus;
import java.time.Instant;
import java.util.List;

/**
 * What the Orders API shows (orders.yaml Order), from the read model or the write-model fallback.
 */
public record OrderView(
    String orderId,
    String customerId,
    OrderStatus status,
    Money total,
    int itemCount,
    Instant placedAt,
    long version,
    List<Line> lines,
    String cancellationReason,
    Shipment shipment,
    boolean invoiceAvailable,
    Money refundedTotal,
    List<TimelineEntry> timeline,
    Source source) {

  /** Where the answer came from. */
  public enum Source {
    READ_MODEL,
    WRITE_MODEL_FALLBACK
  }

  /** One order line. */
  public record Line(
      String lineId,
      String sku,
      String productName,
      int quantity,
      Money unitPrice,
      Money lineTotal,
      int returnedQuantity) {}

  /** Carrier and tracking. */
  public record Shipment(String carrier, String trackingNumber, String status) {}

  /** One timeline entry. */
  public record TimelineEntry(Instant at, String kind, String description, String eventId) {}

  public boolean terminal() {
    return status == OrderStatus.DELIVERED
        || status == OrderStatus.CANCELLED
        || status == OrderStatus.RETURNED
        || status == OrderStatus.PARTIALLY_RETURNED;
  }
}
