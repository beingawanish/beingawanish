package com.edacommerce.payment.domain;

/**
 * Lifecycle of a payment. UNKNOWN is the honest state after a PSP timeout: the money may or may not
 * be held, and only reconciliation can tell (architecture §5.6).
 */
public enum PaymentStatus {
  PENDING,
  UNKNOWN,
  AUTHORIZED,
  DECLINED,
  VOIDED,
  CAPTURE_PENDING,
  CAPTURED,
  CAPTURE_FAILED
}
