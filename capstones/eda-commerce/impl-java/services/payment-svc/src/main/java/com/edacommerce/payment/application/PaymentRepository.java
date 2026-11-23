package com.edacommerce.payment.application;

import com.edacommerce.payment.domain.Payment;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** Port: payments, row-locked on load. */
public interface PaymentRepository {
  Optional<Payment> findForUpdate(String paymentId);

  void save(Payment payment);

  /** PENDING/UNKNOWN payments due for a PSP status query, locked with SKIP LOCKED. */
  List<String> lockDueForReconciliation(Instant now, int limit);

  /** Audit log of PSP calls (payment_attempt). */
  void recordAttempt(String paymentId, String operation, String outcome, Instant at);
}
