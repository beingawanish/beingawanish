package com.edacommerce.notification.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.notification.domain.Contact;
import com.edacommerce.notification.domain.NotificationException;
import com.edacommerce.notification.domain.NotificationPolicy;
import com.edacommerce.notification.domain.Template;
import com.edacommerce.notification.domain.Trigger;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/** Layer 1: which fact gets which message, and the dedupe keys. */
class NotificationPolicyTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  static Optional<NotificationPolicy.Plan> react(Trigger t) {
    return NotificationPolicy.react(t, "Ada");
  }

  @Test
  void everyCustomerFacingFactHasItsTemplate() {
    List<Trigger> triggers =
        List.of(
            new Trigger.OrderConfirmed("o1"),
            new Trigger.OrderCancelled("o1", "PAYMENT_DECLINED"),
            new Trigger.OrderShipped("o1", "s1", "fake-carrier", "FC1"),
            new Trigger.InvoiceIssued("o1", "i1", "INV-2026-000001"),
            new Trigger.OrderDelivered("o1", T),
            new Trigger.ShipmentProblem("o1", "s1", true, "LOST"),
            new Trigger.ReturnLabelIssued("o1", "r1", "s2", "FC2"),
            new Trigger.ReturnAuthorized("o1", "r1", "RMA-2026-000042", T),
            new Trigger.ReturnRejected("o1", "r1", "outside the window"),
            new Trigger.ReturnRefunded("o1", "r1", 12999, "EUR"),
            new Trigger.ReturnClosed("o1", "r1", "EXPIRED"));
    assertThat(triggers.stream().map(t -> react(t).orElseThrow().template()))
        .containsExactly(
            Template.ORDER_CONFIRMED,
            Template.ORDER_CANCELLED,
            Template.ORDER_SHIPPED,
            Template.INVOICE,
            Template.ORDER_DELIVERED,
            Template.SHIPMENT_PROBLEM,
            Template.RETURN_LABEL,
            Template.RETURN_AUTHORIZED,
            Template.RETURN_REJECTED,
            Template.RETURN_REFUNDED,
            Template.RETURN_EXPIRED);
    assertThat(react(new Trigger.ReturnRefunded("o1", "r1", 12999, "EUR")).orElseThrow().body())
        .contains("129.99 EUR");
  }

  @Test
  void documentsAreAttachedOnlyToInvoicesAndReturnLabels() {
    assertThat(react(new Trigger.InvoiceIssued("o1", "i1", "INV")).orElseThrow().attachmentWanted())
        .isTrue();
    assertThat(
            react(new Trigger.ReturnLabelIssued("o1", "r1", "s2", "FC2"))
                .orElseThrow()
                .attachmentWanted())
        .isTrue();
    assertThat(react(new Trigger.OrderConfirmed("o1")).orElseThrow().attachmentWanted()).isFalse();
  }

  @Test
  void operationalFactsSendNothing() {
    assertThat(react(new Trigger.ShipmentProblem("o1", "s1", true, "BOOKING_FAILED"))).isEmpty();
    assertThat(react(new Trigger.ShipmentProblem("o1", "s1", false, "LOST"))).isEmpty();
    assertThat(react(new Trigger.ReturnClosed("o1", "r1", "REFUNDED"))).isEmpty();
  }

  @Test
  void theDedupeKeyIsTheTemplateAndTheBusinessId() {
    assertThat(react(new Trigger.InvoiceIssued("o1", "i1", "INV")).orElseThrow().dedupeKey())
        .isEqualTo("invoice:i1");
    assertThat(react(new Trigger.OrderConfirmed("o1")).orElseThrow().dedupeKey())
        .isEqualTo("order-confirmed:o1");
  }

  @Test
  void contactsExpireAndNeverPrintPersonalData() {
    Contact c = Contact.fromOrder("o1", "c1", "ada@example.com", "Ada", T, Duration.ofDays(400));
    assertThat(c.retainUntil()).isEqualTo(T.plus(Duration.ofDays(400)));
    assertThat(c.toString()).doesNotContain("ada@example.com").doesNotContain("Ada");
    assertThatThrownBy(() -> Contact.fromOrder("o1", "c1", " ", "Ada", T, Duration.ofDays(1)))
        .isInstanceOf(NotificationException.class);
  }
}
