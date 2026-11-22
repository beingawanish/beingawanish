package com.edacommerce.payment.application;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.kernel.Money;
import com.edacommerce.payment.domain.Payment;
import com.edacommerce.payment.domain.PaymentException;
import com.edacommerce.payment.domain.PspAction;
import com.edacommerce.payment.domain.Refund;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.transaction.annotation.Transactional;

/**
 * payment-svc use cases. Each command runs in the consumer's transaction. PSP calls are made inside
 * it: they are idempotent on paymentId/refundId, so a rollback followed by redelivery repeats the call
 * safely, and the transaction holds at most the 5 s PSP timeout (guide §6.5).
 */
public class PaymentUseCases {
  private final PaymentRepository payments;
  private final RefundRepository refunds;
  private final PaymentGateway psp;
  private final PspNotifications notifications;
  private final OutboxWriter outbox;
  private final Clock clock;
  private final Payment.ReconciliationPolicy policy;

  public PaymentUseCases(
      PaymentRepository payments,
      RefundRepository refunds,
      PaymentGateway psp,
      PspNotifications notifications,
      OutboxWriter outbox,
      Clock clock,
      Payment.ReconciliationPolicy policy) {
    this.payments = payments;
    this.refunds = refunds;
    this.psp = psp;
    this.notifications = notifications;
    this.outbox = outbox;
    this.clock = clock;
    this.policy = policy;
  }

  @Transactional
  public Payment authorize(String orderId, String paymentId, String customerId, Money amount, String token, Causation causation) {
    Optional<Payment> existing = payments.findForUpdate(paymentId);
    if (existing.isPresent()) {
      return apply(existing.get().resendAuthorize(), causation);
    }
    Instant now = clock.instant();
    Payment requested = Payment.requested(paymentId, orderId, customerId, amount, token, now);
    payments.save(requested);
    Payment.AuthorizeResult result = psp.authorize(paymentId, amount, token);
    payments.recordAttempt(paymentId, "authorize", result.getClass().getSimpleName(), now);
    return apply(requested.onAuthorizeResult(result, policy, clock.instant()), causation);
  }

  @Transactional
  public Payment capture(String paymentId, Causation causation) {
    Payment p = payments.findForUpdate(paymentId).orElseThrow(() -> new RetryLaterException("unknown payment " + paymentId));
    Payment.Decision d = p.capture(clock.instant());
    if (d.notYet()) {
      throw new RetryLaterException("payment " + paymentId + " not yet authorised");
    }
    return apply(d, causation);
  }

  @Transactional
  public Payment voidPayment(String orderId, String paymentId, Money amountIfUnknown, Causation causation) {
    Instant now = clock.instant();
    try {
      Payment.Decision d =
          payments.findForUpdate(paymentId).map(p -> p.voidPayment(now)).orElseGet(() -> Payment.voidUnknown(paymentId, orderId, amountIfUnknown, now));
      return apply(d, causation);
    } catch (PaymentException e) {
      throw new NonRetryableException(e.getMessage(), e);
    }
  }

  @Transactional
  public Refund refund(String paymentId, String refundId, String returnId, Money amount, String reason, Causation causation) {
    Payment p = payments.findForUpdate(paymentId).orElseThrow(() -> new RetryLaterException("unknown payment " + paymentId));
    Refund.Decision d = Refund.request(refunds.findForUpdate(refundId), p, refundId, returnId, amount, reason, clock.instant());
    if (d.changed()) {
      refunds.save(d.refund());
    }
    if (d.callPsp()) {
      psp.refund(refundId, paymentId, amount);
      payments.recordAttempt(paymentId, "refund", "accepted", clock.instant());
    }
    if (d.reply()) {
      outbox.append(PaymentMessages.refund(d.refund()), causation);
    }
    return d.refund();
  }

  /** Applies stored webhooks (after the endpoint acknowledged them). Returns how many were applied. */
  @Transactional
  public int processNotifications(int limit) {
    List<PspNotifications.Stored> batch = notifications.lockUnprocessed(limit);
    for (PspNotifications.Stored n : batch) {
      switch (n) {
        case PspNotifications.Stored.ForPayment fp ->
            payments.findForUpdate(fp.paymentId()).ifPresent(p -> apply(p.onNotification(fp.notification(), clock.instant()), Causation.root(p.orderId())));
        case PspNotifications.Stored.ForRefund fr ->
            refunds.findForUpdate(fr.refundId()).ifPresent(r -> {
              Refund.Decision d = r.onResult(fr.succeeded(), fr.pspReference(), fr.failure(), fr.retryable(), clock.instant());
              if (d.changed()) {
                refunds.save(d.refund());
              }
              if (d.reply()) {
                outbox.append(PaymentMessages.refund(d.refund()), Causation.root(r.orderId()));
              }
            });
        case PspNotifications.Stored.Ignored ignored -> { }
      }
      notifications.markProcessed(n.pspEventId());
    }
    return batch.size();
  }

  /** One reconciliation pass over unknown and long-pending outcomes (architecture §5.6). */
  @Transactional
  public int reconcileDue(int limit) {
    List<String> due = payments.lockDueForReconciliation(clock.instant(), limit);
    for (String id : due) {
      payments.findForUpdate(id).ifPresent(p -> {
        Payment.PspStatus status = psp.status(id);
        payments.recordAttempt(id, "status", status.getClass().getSimpleName(), clock.instant());
        apply(p.onReconcile(status, policy, clock.instant()), Causation.root(p.orderId()));
      });
    }
    return due.size();
  }

  private Payment apply(Payment.Decision d, Causation causation) {
    Payment p = d.payment();
    if (d.changed()) {
      payments.save(p);
    }
    for (PspAction action : d.actions()) {
      switch (action) {
        case CAPTURE -> psp.capture(p.paymentId(), p.pspReference(), p.amount());
        case VOID -> psp.voidAuthorization(p.paymentId());
      }
      payments.recordAttempt(p.paymentId(), action.name().toLowerCase(java.util.Locale.ROOT), "sent", clock.instant());
    }
    d.events().forEach(e -> outbox.append(PaymentMessages.event(p, e), causation));
    return p;
  }
}
