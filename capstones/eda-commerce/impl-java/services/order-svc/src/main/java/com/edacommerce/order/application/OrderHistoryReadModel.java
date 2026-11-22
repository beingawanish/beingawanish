package com.edacommerce.order.application;

import com.edacommerce.order.domain.OrderStatus;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/** Port: the order-history projection (schema order_history, ADR-0010). */
public interface OrderHistoryReadModel {
  Optional<OrderView> find(String orderId);

  /** Newest first, keyset-paginated after (placedAt, orderId). */
  List<OrderView> listForCustomer(
      String customerId,
      Set<OrderStatus> statuses,
      Instant beforePlacedAt,
      String beforeOrderId,
      int limit);
}
