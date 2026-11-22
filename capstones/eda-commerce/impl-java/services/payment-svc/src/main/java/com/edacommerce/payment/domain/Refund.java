package com.edacommerce.payment.domain;

import com.edacommerce.kernel.Money;
import java.time.Instant;
import java.util.Optional;

/**
 * A refund, idempotent on refundId: the returns saga reuses it on every retry and it is the PSP
 * idempotency key, so a "failed" attempt that actually succeeded can never refund twice (§6.4).
 */
public record Refund(
    String refundId,
    String paymentId,
    String orderId,
    String returnId,
    Money amount,
    String reason,
    Status status,
    String pspReference,
    String failureReason,
    boolean retryable,
    Instant changedAt) {

  public enum Status {
    PENDING,
    SUCCEEDED,
    FAILED
  }

  /** {@code callPsp}: send the refund to the PSP; {@code reply}: re-emit the stored outcome. */
  public record Decision(Refund refund, boolean callPsp, boolean reply, boolean changed) {}

  public static Decision request(
      Optional<Refund> existing,
      Payment payment,
      String refundId,
      String returnId,
      Money amount,
      String reason,
      Instant now) {
    if (existing.isPresent()) {
      Refund r = existing.get();
      return switch (r.status) {
        case PENDING -> new Decision(r, false, false, false);
        case SUCCEEDED -> new Decision(r, false, true, false);
        case FAILED ->
            r.retryable
                ? new Decision(
                    r.with(Status.PENDING, r.pspReference, null, false, now), true, false, true)
                : new Decision(r, false, true, false);
      };
    }
    Refund r =
        new Refund(
            refundId,
            payment.paymentId(),
            payment.orderId(),
            returnId,
            amount,
            reason,
            Status.PENDING,
            null,
            null,
            false,
            now);
    if (payment.status() != PaymentStatus.CAPTURED) {
      return new Decision(
          r.with(Status.FAILED, null, "payment not captured", false, now), false, true, true);
    }
    if (amount.compareTo(payment.amount()) > 0 || amount.amountMinor() <= 0) {
      return new Decision(
          r.with(Status.FAILED, null, "amount outside captured amount", false, now),
          false,
          true,
          true);
    }
    return new Decision(r, true, false, true);
  }

  public Decision onResult(
      boolean succeeded, String pspRef, String failure, boolean retryableFailure, Instant now) {
    if (status != Status.PENDING) {
      return new Decision(this, false, false, false);
    }
    return succeeded
        ? new Decision(with(Status.SUCCEEDED, pspRef, null, false, now), false, true, true)
        : new Decision(
            with(Status.FAILED, pspRef, failure, retryableFailure, now), false, true, true);
  }

  private Refund with(Status s, String pspRef, String failure, boolean retry, Instant now) {
    return new Refund(
        refundId, paymentId, orderId, returnId, amount, reason, s, pspRef, failure, retry, now);
  }
}
