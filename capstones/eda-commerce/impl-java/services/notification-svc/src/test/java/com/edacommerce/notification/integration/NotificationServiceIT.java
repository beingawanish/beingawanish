package com.edacommerce.notification.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.common.Address;
import com.edacommerce.common.ClaimCheck;
import com.edacommerce.common.LineItem;
import com.edacommerce.common.Money;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.InMemoryClaimCheckStore;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.notification.NotificationSent;
import com.edacommerce.notification.adapters.out.mail.fake.FakeMailGateway;
import com.edacommerce.notification.application.MailGateway;
import com.edacommerce.notification.application.NotificationUseCases;
import com.edacommerce.order.InvoiceIssued;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.payment.PaymentVoided;
import com.edacommerce.shipping.ShipmentCreated;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.ApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

/** notification-svc checklist: one email per triggering fact under duplicates; no PII in logs. */
@EdaServiceTest
@ExtendWith(OutputCaptureExtension.class)
class NotificationServiceIT {
  static final String EMAIL = "ada.lovelace.secret@example.com";

  @Autowired ApplicationContext ctx;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired FakeMailGateway mail;
  @Autowired InMemoryClaimCheckStore documents;
  @Autowired NotificationUseCases useCases;
  MessageDriver driver;

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
  }

  @AfterEach
  void reset() {
    clock.reset();
  }

  OrderPlaced placed(String orderId) {
    Money price = new Money(12999L, "EUR");
    return OrderPlaced.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setCustomerId("cust-" + orderId)
        .setLines(List.of(new LineItem("l1", "SKU-1001", "Mug", 1, price, price)))
        .setTotal(price)
        .setShippingAddress(
            Address.newBuilder()
                .setRecipientName("Ada Lovelace")
                .setLine1("Main St 1")
                .setCity("Berlin")
                .setPostalCode("10115")
                .setCountryCode("DE")
                .build())
        .setContactEmail(EMAIL)
        .setShippingMethod(ShippingMethod.STANDARD)
        .setPlacedAt(clock.instant())
        .build();
  }

  OrderConfirmed confirmed(String orderId) {
    return OrderConfirmed.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setReservationId("r")
        .setPaymentId("p")
        .setFulfilmentId("f")
        .setConfirmedAt(clock.instant())
        .build();
  }

  List<MailGateway.Email> mailsFor(String key) {
    return mail.delivered().stream().filter(m -> m.idempotencyKey().endsWith(key)).toList();
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void oneEmailPerFactUnderDuplicatesAndNoPersonalDataInTheLogs(CapturedOutput output) {
    String orderId = Ids.newId();
    driver.deliver("order.events.v1", orderId, placed(orderId));
    MessageDriver.Delivery d = driver.deliver("order.events.v1", orderId, confirmed(orderId));
    assertThat(d.outcome()).isEqualTo(Outcome.SUCCESS);
    assertThat(driver.redeliver(d).outcome()).isEqualTo(Outcome.DUPLICATE);
    // The same fact re-emitted by its producer with a new eventId.
    driver.deliver("order.events.v1", orderId, confirmed(orderId));

    List<MailGateway.Email> mails = mailsFor("order-confirmed:" + orderId);
    assertThat(mails).hasSize(1);
    assertThat(mails.get(0).to()).isEqualTo(EMAIL);
    assertThat(mails.get(0).body()).contains("Ada Lovelace");
    List<NotificationSent> sent = driver.published(NotificationSent.class, orderId);
    assertThat(sent).hasSize(1);
    assertThat(sent.get(0).getTemplate()).isEqualTo("order-confirmed");
    assertThat(sent.get(0).getSourceEventId()).isEqualTo(d.eventId());
    assertThat(sent.get(0).getCustomerId()).isEqualTo("cust-" + orderId);
    assertThat(sent.get(0).getEnvelope().getCausationId()).isEqualTo(d.eventId());
    assertThat(sent.get(0).getEnvelope().getProducer()).isEqualTo("notification-svc");

    assertThat(output.getAll()).contains("order-confirmed").doesNotContain(EMAIL);
    assertThat(output.getAll()).doesNotContain("Ada Lovelace").doesNotContain("Main St 1");
  }

  @Test
  void theInvoiceIsFetchedVerifiedAndAttached() {
    String orderId = Ids.newId();
    driver.deliver("order.events.v1", orderId, placed(orderId));
    byte[] pdf = "%PDF-1.4 invoice".getBytes(java.nio.charset.StandardCharsets.US_ASCII);
    ClaimCheck doc =
        documents.put(
            "invoices", "order/2026/11/" + orderId + "/i1.pdf", pdf, "application/pdf", null);
    InvoiceIssued issued =
        InvoiceIssued.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setInvoiceId("i-" + orderId)
            .setInvoiceNumber("INV-2026-000042")
            .setTotal(new Money(12999L, "EUR"))
            .setDocument(doc)
            .setIssuedAt(clock.instant())
            .build();
    driver.deliver("order.events.v1", orderId, issued);
    MailGateway.Email email = mailsFor("invoice:i-" + orderId).get(0);
    assertThat(email.attachments()).hasSize(1);
    assertThat(email.attachments().get(0).content()).isEqualTo(pdf);
    assertThat(email.attachments().get(0).filename()).isEqualTo("INV-2026-000042.pdf");
    assertThat(driver.published(NotificationSent.class, orderId).get(0).getAttachmentCount())
        .isEqualTo(1);
  }

  @Test
  void aMissingAttachmentRetriesLaterAndATamperedOneIsParked() {
    String orderId = Ids.newId();
    driver.deliver("order.events.v1", orderId, placed(orderId));
    ClaimCheck label =
        documents.put(
            "shipping-labels",
            "shipping/2026/11/" + orderId + "/s1.pdf",
            new byte[] {1, 2, 3, 4},
            "application/pdf",
            Instant.now().plus(Duration.ofDays(30)));
    ClaimCheck missing = ClaimCheck.newBuilder(label).setObjectKey("shipping/none.pdf").build();
    assertThatThrownBy(
            () -> driver.deliver("shipping.events.v1", orderId, returnLabel(orderId, missing)))
        .isInstanceOf(RetryLaterException.class);
    documents.corrupt("shipping-labels", label.getObjectKey());
    assertThatThrownBy(
            () -> driver.deliver("shipping.events.v1", orderId, returnLabel(orderId, label)))
        .isInstanceOf(NonRetryableException.class);
    assertThat(driver.published(NotificationSent.class, orderId)).isEmpty();
  }

  ShipmentCreated returnLabel(String orderId, ClaimCheck label) {
    return ShipmentCreated.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setShipmentId("s-" + orderId)
        .setDirection(ShipmentDirection.RETURN)
        .setFulfilmentId(null)
        .setReturnId("r-" + orderId)
        .setCarrier("fake-carrier")
        .setTrackingNumber("FC000000000042")
        .setLabel(label)
        .setCreatedAt(clock.instant())
        .build();
  }

  @Test
  void theReturnLabelIsEmailedWithThePdf() {
    String orderId = Ids.newId();
    driver.deliver("order.events.v1", orderId, placed(orderId));
    ClaimCheck label =
        documents.put(
            "shipping-labels",
            "shipping/2026/11/" + orderId + "/s.pdf",
            "%PDF-label".getBytes(java.nio.charset.StandardCharsets.US_ASCII),
            "application/pdf",
            null);
    driver.deliver(
        "shipping.events.v1", orderId, returnLabel(orderId, label), "r-" + orderId, null);
    MailGateway.Email email = mailsFor("return-label:s-" + orderId).get(0);
    assertThat(email.attachments()).hasSize(1);
    NotificationSent sent = driver.published(NotificationSent.class, orderId).get(0);
    assertThat(sent.getTemplate()).isEqualTo("return-label");
    assertThat(sent.getEnvelope().getCorrelationId()).isEqualTo("r-" + orderId);
  }

  @Test
  void factsBeforeTheContactWaitAndUnknownTypesAreIgnored() {
    String orderId = Ids.newId();
    assertThatThrownBy(() -> driver.deliver("order.events.v1", orderId, confirmed(orderId)))
        .isInstanceOf(RetryLaterException.class);
    PaymentVoided voided =
        PaymentVoided.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setPaymentId("p")
            .setVoidedAt(clock.instant())
            .build();
    assertThat(driver.deliver("payment.events.v1", orderId, voided).outcome())
        .isEqualTo(Outcome.IGNORED);
  }

  @Test
  void contactsAreForgottenAfterTheirRetention() {
    String orderId = Ids.newId();
    driver.deliver("order.events.v1", orderId, placed(orderId));
    clock.advance(Duration.ofDays(401));
    assertThat(useCases.forgetExpiredContacts()).isGreaterThanOrEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM contact WHERE order_id = ?", Integer.class, orderId))
        .isZero();
  }
}
