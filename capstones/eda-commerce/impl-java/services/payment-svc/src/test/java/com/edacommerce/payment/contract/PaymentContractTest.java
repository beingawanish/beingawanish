package com.edacommerce.payment.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.kernel.Money;
import com.edacommerce.payment.AuthorizePayment;
import com.edacommerce.payment.CapturePayment;
import com.edacommerce.payment.RefundPayment;
import com.edacommerce.payment.VoidPayment;
import com.edacommerce.payment.application.PaymentMessages;
import com.edacommerce.payment.domain.DeclineCode;
import com.edacommerce.payment.domain.Payment;
import com.edacommerce.payment.domain.PaymentEvent;
import com.edacommerce.payment.domain.Refund;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

class PaymentContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @Test
  void consumedCommandsDecodeFromTheirGoldenBytes() {
    assertThat(
            GoldenFixtures.assertSpecificRoundTrip(AuthorizePayment.class).getPaymentMethodToken())
        .isEqualTo("tok_visa_ok");
    GoldenFixtures.assertSpecificRoundTrip(CapturePayment.class);
    GoldenFixtures.assertSpecificRoundTrip(VoidPayment.class);
    GoldenFixtures.assertSpecificRoundTrip(RefundPayment.class);
  }

  @Test
  void everyProducedEventValidates() {
    Payment p = Payment.requested("p1", "o1", "c1", Money.of(100, "EUR"), "tok", T);
    for (PaymentEvent e :
        List.of(
            new PaymentEvent.Authorized("psp", Money.of(100, "EUR"), T, T),
            new PaymentEvent.Declined(DeclineCode.PSP_TIMEOUT, null, T),
            new PaymentEvent.Captured(Money.of(100, "EUR"), "psp", T),
            new PaymentEvent.CaptureFailed(true, false, T),
            new PaymentEvent.Voided(T))) {
      OutgoingMessage m = PaymentMessages.event(p, e);
      assertThat(m.topic()).isEqualTo("payment.events.v1");
      assertThat(m.key()).isEqualTo("o1");
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
    for (Refund.Status s : List.of(Refund.Status.SUCCEEDED, Refund.Status.FAILED)) {
      GoldenFixtures.assertValidAgainstBundled(
          PaymentMessages.refund(
                  new Refund("rf", "p1", "o1", null, Money.of(1, "EUR"), "r", s, "x", "f", true, T))
              .record());
    }
  }
}
