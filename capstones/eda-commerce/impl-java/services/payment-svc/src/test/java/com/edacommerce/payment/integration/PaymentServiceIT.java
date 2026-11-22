package com.edacommerce.payment.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.common.Money;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import com.edacommerce.payment.AuthorizePayment;
import com.edacommerce.payment.CaptureFailureReason;
import com.edacommerce.payment.CapturePayment;
import com.edacommerce.payment.DeclineReason;
import com.edacommerce.payment.PaymentAuthorized;
import com.edacommerce.payment.PaymentCaptureFailed;
import com.edacommerce.payment.PaymentCaptured;
import com.edacommerce.payment.PaymentDeclined;
import com.edacommerce.payment.PaymentVoided;
import com.edacommerce.payment.RefundPayment;
import com.edacommerce.payment.RefundSucceeded;
import com.edacommerce.payment.VoidPayment;
import com.edacommerce.payment.adapters.out.psp.fake.FakePsp;
import com.edacommerce.payment.adapters.out.psp.fake.PspWebhookTransport;
import com.edacommerce.payment.application.PaymentUseCases;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/** payment-svc checklist: decline, timeout paths, duplicate webhooks, late success, bad signature. */
@EdaServiceTest
@Import(PaymentServiceIT.Webhooks.class)
@TestPropertySource(properties = {
  "payment.psp.request-timeout=50ms", "payment.fake-psp.api-latency-ms=0", "payment.fake-psp.webhook-delay-ms=0",
  "payment.fake-psp.decline-rate=0", "payment.fake-psp.timeout-rate=0", "payment.fake-psp.duplicate-webhook-rate=0"})
class PaymentServiceIT {
  /** One captured webhook. */
  record Sent(byte[] body, long ts, String signature) {}

  static final List<Sent> SENT = new CopyOnWriteArrayList<>();

  @TestConfiguration
  static class Webhooks {
    @Bean
    @org.springframework.context.annotation.Primary
    PspWebhookTransport capturingTransport() {
      return (body, ts, sig) -> SENT.add(new Sent(body, ts, sig));
    }
  }

  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired MutableClock clock;
  @Autowired PaymentUseCases useCases;
  @Autowired FakePsp psp;
  @Autowired WebhookVerifier verifier;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  MessageDriver driver;

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
    SENT.clear();
  }

  @AfterEach
  void reset() {
    clock.reset();
    psp.update(new com.edacommerce.payment.adapters.out.psp.fake.FakePspConfig(0.0, 0.0, 0.0, 0, 90_000, 0));
  }

  String authorize(String orderId, String token) {
    String paymentId = Ids.newId();
    driver.deliver("payment.commands.v1", orderId, AuthorizePayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setCustomerId("c1").setAmount(new Money(12999L, "EUR"))
        .setPaymentMethodToken(token).build());
    return paymentId;
  }

  int deliverWebhooks(int expected) throws Exception {
    await().atMost(Duration.ofSeconds(10)).until(() -> SENT.size() >= expected);
    for (Sent s : List.copyOf(SENT)) {
      postWebhook(s.body(), s.ts(), s.signature()).andExpect(status().isOk());
    }
    int n = SENT.size();
    SENT.clear();
    useCases.processNotifications(100);
    return n;
  }

  org.springframework.test.web.servlet.ResultActions postWebhook(byte[] body, long ts, String sig) throws Exception {
    return mvc.perform(post("/webhooks/psp").contentType(MediaType.APPLICATION_JSON).content(body)
        .header("X-Webhook-Timestamp", Long.toString(ts)).header("X-Psp-Signature", sig));
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void happyAuthorisationThenCaptureThenRefund() throws Exception {
    String orderId = Ids.newId();
    String paymentId = authorize(orderId, "tok_visa_ok");
    deliverWebhooks(1);
    PaymentAuthorized a = driver.published(PaymentAuthorized.class, orderId).get(0);
    assertThat(a.getPaymentId()).isEqualTo(paymentId);
    assertThat(a.getEnvelope().getProducer()).isEqualTo("payment-svc");

    driver.deliver("payment.commands.v1", orderId, CapturePayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setAmount(new Money(12999L, "EUR")).build());
    deliverWebhooks(1);
    assertThat(driver.published(PaymentCaptured.class, orderId)).hasSize(1);

    driver.deliver("payment.commands.v1", orderId, RefundPayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setRefundId("rf-" + orderId).setReturnId("ret").setAmount(new Money(5000L, "EUR"))
        .setReason("return").build());
    deliverWebhooks(1);
    assertThat(driver.published(RefundSucceeded.class, orderId)).singleElement()
        .satisfies(r -> assertThat(r.getAmount().getAmountMinor()).isEqualTo(5000L));
  }

  @Test
  void declineIsReportedAsPaymentDeclined() throws Exception {
    String orderId = Ids.newId();
    authorize(orderId, "tok_decline");
    deliverWebhooks(1);
    assertThat(driver.published(PaymentDeclined.class, orderId)).singleElement()
        .satisfies(d -> assertThat(d.getReason()).isEqualTo(DeclineReason.CARD_DECLINED));
  }

  @Test
  void duplicateWebhooksTimesThreeYieldExactlyOnePaymentAuthorized() throws Exception {
    String orderId = Ids.newId();
    authorize(orderId, "tok_dup_webhook");
    assertThat(deliverWebhooks(3)).isEqualTo(3);
    assertThat(driver.published(PaymentAuthorized.class, orderId)).hasSize(1);
    assertThat(jdbc.queryForObject("SELECT count(*) FROM psp_webhook", Integer.class)).isGreaterThanOrEqualTo(1);
  }

  @Test
  void badSignatureAndStaleTimestampAre401() throws Exception {
    byte[] body = "{\"pspEventId\":\"x\",\"eventType\":\"authorization.succeeded\",\"merchantReference\":\"p\"}".getBytes(StandardCharsets.UTF_8);
    long now = clock.instant().getEpochSecond();
    postWebhook(body, now, "deadbeef").andExpect(status().isUnauthorized());
    postWebhook(body, now - 301, verifier.sign(now - 301, body)).andExpect(status().isUnauthorized());
    postWebhook("not json".getBytes(StandardCharsets.UTF_8), now, verifier.sign(now, "not json".getBytes(StandardCharsets.UTF_8)))
        .andExpect(status().isBadRequest());
  }

  @Test
  void timeoutReconcilesToAuthorised() {
    String orderId = Ids.newId();
    String paymentId = authorize(orderId, "tok_timeout");
    assertThat(jdbc.queryForObject("SELECT status FROM payment WHERE payment_id = ?", String.class, paymentId)).isEqualTo("UNKNOWN");
    clock.advance(Duration.ofSeconds(16));
    useCases.reconcileDue(10);
    assertThat(driver.published(PaymentAuthorized.class, orderId)).isEmpty();
    clock.advance(Duration.ofSeconds(16));
    useCases.reconcileDue(10);
    assertThat(driver.published(PaymentAuthorized.class, orderId)).hasSize(1);
  }

  @Test
  void lostRequestEndsPspTimeoutWithVoidAndALateSuccessIsVoided() throws Exception {
    mvc.perform(put("/admin/fakes/psp").contentType(MediaType.APPLICATION_JSON).content("{\"timeoutRate\":1.0}"))
        .andExpect(status().isOk());
    mvc.perform(get("/admin/fakes/psp")).andExpect(status().isOk()).andExpect(OpenApiContract.validResponse("admin.yaml"));
    String orderId = Ids.newId();
    String paymentId = authorize(orderId, "tok_random");
    for (int i = 0; i < 9; i++) {
      clock.advance(Duration.ofSeconds(15));
      useCases.reconcileDue(10);
    }
    assertThat(driver.published(PaymentDeclined.class, orderId)).singleElement()
        .satisfies(d -> assertThat(d.getReason()).isEqualTo(DeclineReason.PSP_TIMEOUT));
    assertThat(psp.isVoided(paymentId)).isTrue();

    byte[] late = ("{\"pspEventId\":\"late-" + paymentId + "\",\"eventType\":\"authorization.succeeded\",\"pspPaymentId\":\"psp\","
        + "\"merchantReference\":\"" + paymentId + "\",\"occurredAt\":\"2026-11-18T09:00:00Z\"}").getBytes(StandardCharsets.UTF_8);
    long ts = clock.instant().getEpochSecond();
    postWebhook(late, ts, verifier.sign(ts, late)).andExpect(status().isOk());
    useCases.processNotifications(10);
    assertThat(driver.published(PaymentAuthorized.class, orderId)).isEmpty();
    assertThat(jdbc.queryForObject("SELECT late_success_voided FROM payment WHERE payment_id = ?", Boolean.class, paymentId)).isTrue();
  }

  @Test
  void captureFailsWithAuthorizationExpiredForTheMagicToken() throws Exception {
    String orderId = Ids.newId();
    String paymentId = authorize(orderId, "tok_capture_fails");
    deliverWebhooks(1);
    driver.deliver("payment.commands.v1", orderId, CapturePayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setAmount(new Money(12999L, "EUR")).build());
    deliverWebhooks(1);
    assertThat(driver.published(PaymentCaptureFailed.class, orderId)).singleElement().satisfies(f -> {
      assertThat(f.getReason()).isEqualTo(CaptureFailureReason.AUTHORIZATION_EXPIRED);
      assertThat(f.getRetryable()).isFalse();
    });
  }

  @Test
  void resendsAndDuplicatesAreSafe() throws Exception {
    String orderId = Ids.newId();
    String paymentId = authorize(orderId, "tok_visa_ok");
    deliverWebhooks(1);
    // Resend: new eventId, same paymentId -> the original reply again, no second PSP call.
    driver.deliver("payment.commands.v1", orderId, AuthorizePayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setCustomerId("c1").setAmount(new Money(12999L, "EUR"))
        .setPaymentMethodToken("tok_visa_ok").build());
    assertThat(driver.published(PaymentAuthorized.class, orderId)).hasSize(2);
    assertThat(jdbc.queryForObject("SELECT count(*) FROM payment_attempt WHERE payment_id = ? AND operation = 'authorize'", Integer.class, paymentId)).isEqualTo(1);

    MessageDriver.Delivery v = driver.deliver("payment.commands.v1", orderId, VoidPayment.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setPaymentId(paymentId).setReason("cancel").build());
    assertThat(driver.redeliver(v).outcome()).isEqualTo(Outcome.DUPLICATE);
    assertThat(driver.published(PaymentVoided.class, orderId)).hasSize(1);
  }
}
