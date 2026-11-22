package com.edacommerce.payment.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.kernel.Money;
import com.edacommerce.payment.domain.DeclineCode;
import com.edacommerce.payment.domain.Payment;
import com.edacommerce.payment.domain.Payment.AuthorizeResult;
import com.edacommerce.payment.domain.Payment.Notification;
import com.edacommerce.payment.domain.Payment.PspStatus;
import com.edacommerce.payment.domain.PaymentEvent;
import com.edacommerce.payment.domain.PaymentException;
import com.edacommerce.payment.domain.PaymentStatus;
import com.edacommerce.payment.domain.PspAction;
import com.edacommerce.payment.domain.Refund;
import java.time.Duration;
import java.time.Instant;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class PaymentTest {
  static final Instant T0 = Instant.parse("2026-11-18T09:00:00Z");
  static final Payment.ReconciliationPolicy POLICY = Payment.ReconciliationPolicy.DEFAULT;
  static final Money AMOUNT = Money.of(12999, "EUR");

  static Payment pending() {
    Payment p = Payment.requested("p1", "o1", "c1", AMOUNT, "tok_visa_ok", T0);
    return p.onAuthorizeResult(new AuthorizeResult.Accepted("psp1"), POLICY, T0).payment();
  }

  static Payment authorized() {
    return pending().onNotification(new Notification.AuthorizationSucceeded("psp1"), T0.plusSeconds(1)).payment();
  }

  @Test
  void webhookSuccessAuthorisesWithASevenDayExpiry() {
    Payment.Decision d = pending().onNotification(new Notification.AuthorizationSucceeded("psp1"), T0.plusSeconds(1));
    assertThat(d.payment().status()).isEqualTo(PaymentStatus.AUTHORIZED);
    assertThat(d.events()).containsExactly(new PaymentEvent.Authorized("psp1", AMOUNT, T0.plusSeconds(1), T0.plusSeconds(1).plus(Duration.ofDays(7))));
  }

  @Test
  void declineIsReportedOnce() {
    Payment.Decision d = pending().onNotification(new Notification.AuthorizationFailed(DeclineCode.CARD_DECLINED), T0);
    assertThat(d.events()).containsExactly(new PaymentEvent.Declined(DeclineCode.CARD_DECLINED, "psp1", T0));
    assertThat(d.payment().onNotification(new Notification.AuthorizationFailed(DeclineCode.CARD_DECLINED), T0).events()).isEmpty();
  }

  @Test
  void duplicateNotificationsHaveNoSecondEffect() {
    Payment a = authorized();
    assertThat(a.onNotification(new Notification.AuthorizationSucceeded("psp1"), T0.plusSeconds(2)).changed()).isFalse();
  }

  @Test
  void timeoutReconcilesToAuthorised() {
    Payment unknown = Payment.requested("p1", "o1", "c1", AMOUNT, "tok_timeout", T0)
        .onAuthorizeResult(new AuthorizeResult.Timeout(), POLICY, T0).payment();
    assertThat(unknown.status()).isEqualTo(PaymentStatus.UNKNOWN);
    assertThat(unknown.nextReconcileAt()).isEqualTo(T0.plusSeconds(15));
    Payment.Decision still = unknown.onReconcile(new PspStatus.Pending(), POLICY, T0.plusSeconds(15));
    assertThat(still.events()).isEmpty();
    assertThat(still.payment().nextReconcileAt()).isEqualTo(T0.plusSeconds(30));
    Payment.Decision ok = still.payment().onReconcile(new PspStatus.Authorized("psp9"), POLICY, T0.plusSeconds(30));
    assertThat(ok.events()).hasOnlyElementsOfType(PaymentEvent.Authorized.class);
  }

  @Test
  void timeoutStillUnknownAfterTheWindowIsVoidedAndDeclinedPspTimeout() {
    Payment unknown = Payment.requested("p1", "o1", "c1", AMOUNT, "tok_x", T0)
        .onAuthorizeResult(new AuthorizeResult.Timeout(), POLICY, T0).payment();
    assertThat(unknown.onReconcile(new PspStatus.NotFound(), POLICY, T0.plusSeconds(60)).events()).isEmpty();
    Payment.Decision d = unknown.onReconcile(new PspStatus.NotFound(), POLICY, T0.plus(Duration.ofMinutes(2)));
    assertThat(d.actions()).containsExactly(PspAction.VOID);
    assertThat(d.events()).containsExactly(new PaymentEvent.Declined(DeclineCode.PSP_TIMEOUT, null, T0.plus(Duration.ofMinutes(2))));
  }

  @Test
  void lateSuccessAfterPspTimeoutIsVoidedAndNeverReported() {
    Payment declined = Payment.requested("p1", "o1", "c1", AMOUNT, "tok_x", T0)
        .onAuthorizeResult(new AuthorizeResult.Timeout(), POLICY, T0).payment()
        .onReconcile(new PspStatus.NotFound(), POLICY, T0.plus(Duration.ofMinutes(3))).payment();
    Payment.Decision late = declined.onNotification(new Notification.AuthorizationSucceeded("psp1"), T0.plus(Duration.ofMinutes(4)));
    assertThat(late.events()).isEmpty();
    assertThat(late.actions()).containsExactly(PspAction.VOID);
    assertThat(late.payment().lateSuccessVoided()).isTrue();
    assertThat(late.payment().status()).isEqualTo(PaymentStatus.DECLINED);
  }

  @Test
  void resendAuthorizeReplaysOrWaits() {
    assertThat(pending().resendAuthorize().events()).isEmpty();
    assertThat(authorized().resendAuthorize().events()).hasOnlyElementsOfType(PaymentEvent.Authorized.class);
  }

  @Test
  void captureIsRetriedOnlyWhenRetryable() {
    Payment.Decision c = authorized().capture(T0.plusSeconds(10));
    assertThat(c.actions()).containsExactly(PspAction.CAPTURE);
    Payment failed = c.payment().onNotification(new Notification.CaptureFailed(false), T0.plusSeconds(11)).payment();
    assertThat(failed.captureFailureRetryable()).isTrue();
    assertThat(failed.capture(T0.plusSeconds(70)).actions()).containsExactly(PspAction.CAPTURE);

    Payment expired = c.payment().onNotification(new Notification.CaptureFailed(true), T0.plusSeconds(11)).payment();
    assertThat(expired.capture(T0.plusSeconds(70)).actions()).isEmpty();
    assertThat(expired.capture(T0.plusSeconds(70)).events()).containsExactly(new PaymentEvent.CaptureFailed(true, false, T0.plusSeconds(11)));
    assertThat(pending().capture(T0).notYet()).isTrue();
  }

  @Test
  void voidIsIdempotentAndRefusedPastThePivot() {
    Payment.Decision v = authorized().voidPayment(T0.plusSeconds(5));
    assertThat(v.actions()).containsExactly(PspAction.VOID);
    assertThat(v.payment().voidPayment(T0.plusSeconds(6)).actions()).isEmpty();
    assertThat(v.payment().voidPayment(T0.plusSeconds(6)).events()).hasOnlyElementsOfType(PaymentEvent.Voided.class);
    assertThat(Payment.voidUnknown("p9", "o9", AMOUNT, T0).payment().resendAuthorize().events()).hasOnlyElementsOfType(PaymentEvent.Voided.class);
    Payment capturing = authorized().capture(T0).payment();
    assertThatThrownBy(() -> capturing.voidPayment(T0)).isInstanceOf(PaymentException.class);
  }

  @Test
  void refundsAreIdempotentOnRefundIdAndNeedACapture() {
    Payment captured = authorized().capture(T0).payment().onNotification(new Notification.CaptureSucceeded("psp1"), T0).payment();
    Refund.Decision first = Refund.request(Optional.empty(), captured, "rf1", "ret1", Money.of(5000, "EUR"), "return", T0);
    assertThat(first.callPsp()).isTrue();
    Refund.Decision resent = Refund.request(Optional.of(first.refund()), captured, "rf1", "ret1", Money.of(5000, "EUR"), "return", T0);
    assertThat(resent.callPsp()).isFalse();
    Refund done = first.refund().onResult(true, "psprf", null, false, T0).refund();
    assertThat(Refund.request(Optional.of(done), captured, "rf1", "ret1", Money.of(5000, "EUR"), "return", T0).reply()).isTrue();
    assertThat(Refund.request(Optional.empty(), authorized(), "rf2", null, Money.of(1, "EUR"), "x", T0).refund().status())
        .isEqualTo(Refund.Status.FAILED);
  }
}
