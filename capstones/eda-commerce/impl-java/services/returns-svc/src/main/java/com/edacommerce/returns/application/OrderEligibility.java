package com.edacommerce.returns.application;

import com.edacommerce.returns.domain.OrderLine;
import com.edacommerce.returns.domain.Pickup;
import java.time.Instant;
import java.util.List;

/** One row of the eligibility view: what returns-svc knows about an order. */
public record OrderEligibility(
    String orderId,
    String customerId,
    String status,
    String paymentId,
    String currency,
    List<OrderLine> lines,
    long shippingFeeMinor,
    Pickup pickup,
    String warehouseId,
    Instant deliveredAt,
    Instant windowEndsAt,
    long version) {

  public boolean delivered() {
    return "DELIVERED".equals(status) && deliveredAt != null;
  }
}
