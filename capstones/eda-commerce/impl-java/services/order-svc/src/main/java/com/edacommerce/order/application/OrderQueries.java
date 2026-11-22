package com.edacommerce.order.application;

import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.Order;
import com.edacommerce.order.domain.OrderStatus;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * The read side of the Orders API. Reads come from the projection; a brand-new order not yet
 * projected falls back to the write model so the client sees PENDING instead of 404 (architecture
 * §9). The fallback reports version 0, so a client never sees the version go backwards when the
 * projection catches up.
 */
public class OrderQueries {
  static final Duration INVOICE_URL_TTL = Duration.ofMinutes(5);

  private final OrderHistoryReadModel readModel;
  private final OrderRepository orders;
  private final InvoiceRepository invoices;
  private final ClaimCheckStore documents;

  public OrderQueries(
      OrderHistoryReadModel readModel,
      OrderRepository orders,
      InvoiceRepository invoices,
      ClaimCheckStore documents) {
    this.readModel = readModel;
    this.orders = orders;
    this.invoices = invoices;
    this.documents = documents;
  }

  /** Empty when the order does not exist or belongs to someone else (both answer 404). */
  public Optional<OrderView> get(String orderId, String callerId) {
    Optional<OrderView> projected = readModel.find(orderId);
    if (projected.isPresent()) {
      return projected.filter(v -> v.customerId().equals(callerId));
    }
    return orders.find(orderId).filter(o -> o.customerId().equals(callerId)).map(this::fallback);
  }

  public Optional<URL> invoiceUrl(String orderId, String callerId) {
    Optional<Order> order = orders.find(orderId).filter(o -> o.customerId().equals(callerId));
    if (order.isEmpty()) {
      return Optional.empty();
    }
    return invoices
        .findByOrder(orderId)
        .map(
            inv ->
                documents.presign(
                    com.edacommerce.common.ClaimCheck.newBuilder()
                        .setBucket(inv.bucket())
                        .setObjectKey(inv.objectKey())
                        .setContentType("application/pdf")
                        .setSizeBytes(inv.sizeBytes())
                        .setSha256(inv.sha256())
                        .setExpiresAt(null)
                        .build(),
                    INVOICE_URL_TTL));
  }

  /** A page of history and the opaque cursor of the next page (null at the end). */
  public record Page(List<OrderView> items, String nextCursor) {}

  public Page list(String callerId, Set<OrderStatus> statuses, String cursor, int limit) {
    Instant before = null;
    String beforeId = null;
    if (cursor != null && !cursor.isBlank()) {
      String[] parts =
          new String(Base64.getUrlDecoder().decode(cursor), StandardCharsets.UTF_8).split("\\|", 2);
      before = Instant.parse(parts[0]);
      beforeId = parts[1];
    }
    List<OrderView> rows =
        readModel.listForCustomer(callerId, statuses, before, beforeId, limit + 1);
    String next = null;
    if (rows.size() > limit) {
      rows = rows.subList(0, limit);
      OrderView last = rows.get(limit - 1);
      next =
          Base64.getUrlEncoder()
              .withoutPadding()
              .encodeToString(
                  (last.placedAt() + "|" + last.orderId()).getBytes(StandardCharsets.UTF_8));
    }
    return new Page(rows, next);
  }

  private OrderView fallback(Order o) {
    OrderStatus status = orders.status(o.orderId()).orElse(OrderStatus.PENDING);
    List<OrderView.Line> lines =
        o.lines().stream()
            .map(
                l ->
                    new OrderView.Line(
                        l.lineId(),
                        l.sku(),
                        l.productName(),
                        l.quantity(),
                        l.unitPrice(),
                        l.lineTotal(),
                        0))
            .toList();
    return new OrderView(
        o.orderId(),
        o.customerId(),
        status,
        o.total(),
        o.itemCount(),
        o.placedAt(),
        0,
        lines,
        null,
        null,
        false,
        Money.zero(o.total().currency()),
        List.of(),
        OrderView.Source.WRITE_MODEL_FALLBACK);
  }
}
