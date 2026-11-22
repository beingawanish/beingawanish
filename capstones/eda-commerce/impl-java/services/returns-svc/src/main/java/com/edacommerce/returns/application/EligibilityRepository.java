package com.edacommerce.returns.application;

import com.edacommerce.returns.domain.OrderLine;
import com.edacommerce.returns.domain.Pickup;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * Port: the eligibility view, a projection of order.events.v1 (ADR-0010). Each fact sets only its
 * own fields, so a fact arriving late through a retry topic is never lost; the status moves only
 * forward in aggregateVersion.
 */
public interface EligibilityRepository {
  Optional<OrderEligibility> findOrder(String orderId);

  /** Row-locks the order: concurrent returns of one order are checked one after the other. */
  Optional<OrderEligibility> findOrderForUpdate(String orderId);

  void placed(
      String orderId,
      String customerId,
      String currency,
      List<OrderLine> lines,
      long shippingFeeMinor,
      Pickup pickup,
      long version);

  /**
   * @return false when the order is unknown (OrderPlaced not projected yet)
   */
  boolean confirmed(String orderId, String paymentId, long version);

  boolean delivered(String orderId, Instant deliveredAt, Instant windowEndsAt, long version);

  boolean cancelled(String orderId, long version);

  boolean warehouse(String orderId, String warehouseId);
}
