package com.edacommerce.payment.application;

import com.edacommerce.common.Money;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.payment.CaptureFailureReason;
import com.edacommerce.payment.DeclineReason;
import com.edacommerce.payment.PaymentAuthorized;
import com.edacommerce.payment.PaymentCaptureFailed;
import com.edacommerce.payment.PaymentCaptured;
import com.edacommerce.payment.PaymentDeclined;
import com.edacommerce.payment.PaymentVoided;
import com.edacommerce.payment.RefundFailed;
import com.edacommerce.payment.RefundSucceeded;
import com.edacommerce.payment.domain.Payment;
import com.edacommerce.payment.domain.PaymentEvent;
import com.edacommerce.payment.domain.Refund;
import org.apache.avro.specific.SpecificRecord;

/** Domain events -> payment.events.v1 messages (key orderId, aggregate Payment). */
public final class PaymentMessages {
  private PaymentMessages() {}

  public static final String TOPIC = "payment.events.v1";

  public static Money money(com.edacommerce.kernel.Money m) {
    return new Money(m.amountMinor(), m.currency());
  }

  public static OutgoingMessage event(Payment p, PaymentEvent e) {
    SpecificRecord r =
        switch (e) {
          case PaymentEvent.Authorized a ->
              PaymentAuthorized.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(p.orderId())
                  .setPaymentId(p.paymentId())
                  .setPspReference(a.pspReference())
                  .setAmount(money(a.amount()))
                  .setAuthorizedAt(a.authorizedAt())
                  .setAuthorizationExpiresAt(a.expiresAt())
                  .build();
          case PaymentEvent.Declined d ->
              PaymentDeclined.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(p.orderId())
                  .setPaymentId(p.paymentId())
                  .setReason(DeclineReason.valueOf(d.reason().name()))
                  .setPspReference(d.pspReference())
                  .setDeclinedAt(d.declinedAt())
                  .build();
          case PaymentEvent.Captured c ->
              PaymentCaptured.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(p.orderId())
                  .setPaymentId(p.paymentId())
                  .setAmount(money(c.amount()))
                  .setPspReference(c.pspReference())
                  .setCapturedAt(c.capturedAt())
                  .build();
          case PaymentEvent.CaptureFailed f ->
              PaymentCaptureFailed.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(p.orderId())
                  .setPaymentId(p.paymentId())
                  .setReason(
                      f.authorizationExpired()
                          ? CaptureFailureReason.AUTHORIZATION_EXPIRED
                          : CaptureFailureReason.PSP_ERROR)
                  .setRetryable(f.retryable())
                  .setFailedAt(f.failedAt())
                  .build();
          case PaymentEvent.Voided v ->
              PaymentVoided.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(p.orderId())
                  .setPaymentId(p.paymentId())
                  .setVoidedAt(v.voidedAt())
                  .build();
        };
    return OutgoingMessage.of(TOPIC, p.orderId(), r, "Payment", p.paymentId(), p.version());
  }

  public static OutgoingMessage refund(Refund r) {
    SpecificRecord rec =
        r.status() == Refund.Status.SUCCEEDED
            ? RefundSucceeded.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(r.orderId())
                .setPaymentId(r.paymentId())
                .setRefundId(r.refundId())
                .setReturnId(r.returnId())
                .setAmount(money(r.amount()))
                .setPspReference(r.pspReference() == null ? "" : r.pspReference())
                .setRefundedAt(r.changedAt())
                .build()
            : RefundFailed.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(r.orderId())
                .setPaymentId(r.paymentId())
                .setRefundId(r.refundId())
                .setReturnId(r.returnId())
                .setReason(r.failureReason() == null ? "unknown" : r.failureReason())
                .setRetryable(r.retryable())
                .setFailedAt(r.changedAt())
                .build();
    return OutgoingMessage.of(TOPIC, r.orderId(), rec, "Refund", r.refundId(), 1);
  }
}
