package com.edacommerce.payment.application;

import com.edacommerce.payment.domain.Refund;
import java.util.Optional;

/** Port: refunds keyed by the returns saga's refundId. */
public interface RefundRepository {
  Optional<Refund> findForUpdate(String refundId);

  void save(Refund refund);
}
