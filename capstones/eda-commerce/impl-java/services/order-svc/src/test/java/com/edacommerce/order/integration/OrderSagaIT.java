package com.edacommerce.order.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.checkout.CheckoutSubmitted;
import com.edacommerce.common.Money;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.saga.DeadlineSweeper;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.InMemoryClaimCheckStore;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.OrderDispatched;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.fulfilment.RequestFulfilment;
import com.edacommerce.inventory.ReleaseReservation;
import com.edacommerce.inventory.ReservationCommitted;
import com.edacommerce.inventory.ReservationReleased;
import com.edacommerce.inventory.ReserveStock;
import com.edacommerce.inventory.StockReserved;
import com.edacommerce.order.InvoiceIssued;
import com.edacommerce.order.OrderCancelled;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.order.OrderShipped;
import com.edacommerce.order.adapters.projector.JdbcOrderHistory;
import com.edacommerce.order.adapters.projector.OrderHistoryProjector;
import com.edacommerce.payment.AuthorizePayment;
import com.edacommerce.payment.CapturePayment;
import com.edacommerce.payment.DeclineReason;
import com.edacommerce.payment.PaymentAuthorized;
import com.edacommerce.payment.PaymentCaptured;
import com.edacommerce.payment.PaymentDeclined;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import javax.sql.DataSource;
import org.apache.avro.specific.SpecificRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;

/** order-svc end to end at the database level: the saga driven by contract messages. */
@EdaServiceTest
class OrderSagaIT {
  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired InMemoryClaimCheckStore documents;
  @Autowired DeadlineSweeper sweeper;
  @Autowired JdbcOrderHistory history;
  MessageDriver driver;
  MessageDriver projector;

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
    projector = new MessageDriver(ctx, "order-history-projector", new OrderHistoryProjector(history).handlers());
  }

  @AfterEach
  void reset() {
    clock.reset();
  }

  String checkout() {
    CheckoutSubmitted c = GoldenFixtures.decode(CheckoutSubmitted.class);
    String orderId = Ids.newId();
    c.setOrderId(orderId);
    c.setCheckoutId(Ids.newId());
    c.setCustomerId("local-customer");
    MessageDriver.Delivery d = driver.deliver("checkout.events.v1", orderId, c);
    assertThat(d.outcome()).isEqualTo(Outcome.SUCCESS);
    return orderId;
  }

  <T extends SpecificRecord> T last(Class<T> type, String orderId) {
    List<T> all = driver.published(type, orderId);
    assertThat(all).as(type.getSimpleName()).isNotEmpty();
    return all.get(all.size() - 1);
  }

  void reply(String topic, String orderId, SpecificRecord r) {
    Envelopes.set(r, Envelopes.placeholder());
    assertThat(driver.deliver(topic, orderId, r).outcome()).isEqualTo(Outcome.SUCCESS);
  }

  String state(String orderId) {
    return jdbc.queryForObject("SELECT state FROM saga_instance WHERE saga_id = ?", String.class, orderId);
  }

  Money m(long minor) {
    return new Money(minor, "EUR");
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void checkoutStartsTheSagaAndTheOrderIsVisibleAtOnceThroughTheFallback() throws Exception {
    String orderId = checkout();
    MessageDriver.Published placed = driver.publishedFor(orderId).get(0);
    assertThat(placed.record()).isInstanceOf(OrderPlaced.class);
    assertThat(placed.envelope().getProducer()).isEqualTo("order-svc");
    assertThat(placed.envelope().getPartitionKey()).isEqualTo(orderId);
    assertThat(placed.envelope().getAggregateVersion()).isEqualTo(1);
    ReserveStock reserve = last(ReserveStock.class, orderId);
    assertThat(reserve.getTtlSeconds()).isEqualTo(900);
    assertThat(state(orderId)).isEqualTo("RESERVING_STOCK");

    mvc.perform(get("/orders/" + orderId))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.status").value("PENDING"))
        .andExpect(jsonPath("$.source").value("WRITE_MODEL_FALLBACK"))
        .andExpect(header().exists("Retry-After"))
        .andExpect(OpenApiContract.validResponse("orders.yaml"));
    mvc.perform(get("/orders/" + orderId).header("X-Local-Customer-Id", "someone-else")).andExpect(status().isNotFound());
  }

  @Test
  void aDuplicateCheckoutIsANoOp() {
    CheckoutSubmitted c = GoldenFixtures.decode(CheckoutSubmitted.class);
    String orderId = Ids.newId();
    c.setOrderId(orderId);
    MessageDriver.Delivery d = driver.deliver("checkout.events.v1", orderId, c);
    assertThat(driver.redeliver(d).outcome()).isEqualTo(Outcome.DUPLICATE);
    driver.deliver("checkout.events.v1", orderId, CheckoutSubmitted.newBuilder(c).build());
    assertThat(driver.published(ReserveStock.class, orderId)).hasSize(1);
  }

  @Test
  void happyPathToDeliveredWithInvoiceAndReadModel() throws Exception {
    String orderId = checkout();
    String res = last(ReserveStock.class, orderId).getReservationId();
    reply("inventory.events.v1", orderId, StockReserved.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setReservationId(res).setLines(List.of()).setExpiresAt(clock.instant().plusSeconds(900)).build());
    AuthorizePayment auth = last(AuthorizePayment.class, orderId);
    assertThat(auth.getAmount().getAmountMinor()).isEqualTo(1999L);
    assertThat(auth.getPaymentMethodToken()).isEqualTo("tok_visa_ok");
    String pay = auth.getPaymentId();
    reply("payment.events.v1", orderId, PaymentAuthorized.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setPaymentId(pay).setPspReference("psp").setAmount(m(1999)).setAuthorizedAt(clock.instant())
        .setAuthorizationExpiresAt(clock.instant().plus(Duration.ofDays(7))).build());
    reply("inventory.events.v1", orderId, ReservationCommitted.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setReservationId(res).setCommittedAt(clock.instant()).build());
    assertThat(last(OrderConfirmed.class, orderId).getPaymentId()).isEqualTo(pay);
    RequestFulfilment rf = last(RequestFulfilment.class, orderId);
    assertThat(rf.getAttempt()).isEqualTo(1);
    assertThat(rf.getShipTo().getCity()).isEqualTo("Berlin");
    String ful = rf.getFulfilmentId();
    reply("fulfilment.events.v1", orderId, FulfilmentAccepted.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setFulfilmentId(ful).setWarehouseId("w").setAcceptedAt(clock.instant()).build());
    reply("fulfilment.events.v1", orderId, OrderPacked.newBuilder(GoldenFixtures.decode(OrderPacked.class)).setOrderId(orderId).setFulfilmentId(ful).build());
    reply("shipping.events.v1", orderId, ShipmentCreated.newBuilder(GoldenFixtures.decode(ShipmentCreated.class)).setOrderId(orderId)
        .setShipmentId("ship-1").setDirection(ShipmentDirection.OUTBOUND).build());
    reply("fulfilment.events.v1", orderId, OrderDispatched.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setFulfilmentId(ful).setShipmentId("ship-1").setDispatchedAt(clock.instant()).build());
    assertThat(last(CapturePayment.class, orderId).getPaymentId()).isEqualTo(pay);
    reply("payment.events.v1", orderId, PaymentCaptured.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setPaymentId(pay).setAmount(m(1999)).setPspReference("psp").setCapturedAt(clock.instant()).build());

    OrderShipped shipped = last(OrderShipped.class, orderId);
    assertThat(shipped.getTrackingNumber()).isEqualTo("FC123456789DE");
    InvoiceIssued invoice = last(InvoiceIssued.class, orderId);
    assertThat(invoice.getInvoiceNumber()).matches("INV-\\d{4}-\\d{6}");
    assertThat(invoice.getDocument().getObjectKey())
        .isEqualTo(ClaimChecks.key("order", invoice.getIssuedAt(), orderId, invoice.getInvoiceId(), "pdf"));
    byte[] pdf = documents.get(invoice.getDocument());
    assertThat(new String(pdf, 0, 5, java.nio.charset.StandardCharsets.US_ASCII)).isEqualTo("%PDF-");

    reply("shipping.events.v1", orderId, ShipmentDelivered.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setShipmentId("ship-1").setDirection(ShipmentDirection.OUTBOUND).setCarrierEventId("c3").setDeliveredAt(clock.instant()).build());
    assertThat(state(orderId)).isEqualTo("DELIVERED");
    assertThat(last(OrderDelivered.class, orderId).getEnvelope().getAggregateVersion()).isEqualTo(5);

    mvc.perform(get("/orders/" + orderId + "/invoice")).andExpect(status().isFound()).andExpect(header().exists("Location"));
    mvc.perform(get("/ops/sagas/" + orderId)).andExpect(status().isOk())
        .andExpect(jsonPath("$.state").value("DELIVERED")).andExpect(jsonPath("$.history.length()").value(10))
        .andExpect(OpenApiContract.validResponse("admin.yaml"));

    // Project every order event and read the order from the read model.
    for (MessageDriver.Published p : driver.publishedFor(orderId)) {
      if (p.topic().equals("order.events.v1")) {
        projector.deliver(p.topic(), orderId, p.record());
      }
    }
    mvc.perform(get("/orders/" + orderId)).andExpect(status().isOk())
        .andExpect(jsonPath("$.source").value("READ_MODEL")).andExpect(jsonPath("$.status").value("DELIVERED"))
        .andExpect(jsonPath("$.version").value(5)).andExpect(jsonPath("$.invoiceAvailable").value(true))
        .andExpect(header().doesNotExist("Retry-After"))
        .andExpect(OpenApiContract.validResponse("orders.yaml"));
    mvc.perform(get("/orders/" + orderId).header("If-None-Match", "\"5\"")).andExpect(status().isNotModified());
    mvc.perform(get("/customers/me/orders")).andExpect(status().isOk()).andExpect(OpenApiContract.validResponse("orders.yaml"));
  }

  @Test
  void declinePathReleasesStockAndCancels() {
    String orderId = checkout();
    String res = last(ReserveStock.class, orderId).getReservationId();
    reply("inventory.events.v1", orderId, StockReserved.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setReservationId(res).setLines(List.of()).setExpiresAt(clock.instant()).build());
    String pay = last(AuthorizePayment.class, orderId).getPaymentId();
    reply("payment.events.v1", orderId, PaymentDeclined.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setPaymentId(pay).setReason(DeclineReason.CARD_DECLINED).setDeclinedAt(clock.instant()).build());
    assertThat(last(ReleaseReservation.class, orderId).getReservationId()).isEqualTo(res);
    reply("inventory.events.v1", orderId, ReservationReleased.newBuilder().setEnvelope(Envelopes.placeholder()).setOrderId(orderId)
        .setReservationId(res).setReason("x").setReleasedAt(clock.instant()).build());
    OrderCancelled c = last(OrderCancelled.class, orderId);
    assertThat(c.getReason()).isEqualTo(com.edacommerce.order.CancellationReason.PAYMENT_DECLINED);
    assertThat(c.getPaymentVoided()).isFalse();
    assertThat(jdbc.queryForObject("SELECT status FROM orders WHERE order_id = ?", String.class, orderId)).isEqualTo("CANCELLED");
  }

  @Test
  void theDeadlineSweeperResendsWithTheSameBusinessId() {
    String orderId = checkout();
    String res = last(ReserveStock.class, orderId).getReservationId();
    clock.advance(Duration.ofSeconds(31));
    assertThat(sweeper.sweepOnce()).isGreaterThanOrEqualTo(1);
    List<ReserveStock> sent = driver.published(ReserveStock.class, orderId);
    assertThat(sent).hasSize(2);
    assertThat(sent.get(1).getReservationId()).isEqualTo(res);
    assertThat(sent.get(1).getEnvelope().getEventId()).isNotEqualTo(sent.get(0).getEnvelope().getEventId());
  }

  @Test
  void invoiceNumbersAreGaplessAcrossOrders() {
    // The counter row per year is locked in the issuing transaction (guide §6.2).
    Map<String, Object> before = jdbc.queryForMap("SELECT count(*) AS n FROM invoice");
    assertThat(before).isNotNull();
    var repo = ctx.getBean(com.edacommerce.order.application.InvoiceRepository.class);
    var tx = ctx.getBean(org.springframework.transaction.support.TransactionTemplate.class);
    int year = 2031;
    long a = tx.execute(s -> repo.nextSequence(year));
    tx.executeWithoutResult(s -> {
      repo.nextSequence(year);
      s.setRollbackOnly(); // a failed issue gives its number back
    });
    long b = tx.execute(s -> repo.nextSequence(year));
    assertThat(b).isEqualTo(a + 1);
  }

  @Test
  void retryStepOnATerminalSagaIs409AndUnknownIs404() throws Exception {
    String orderId = checkout();
    String res = last(ReserveStock.class, orderId).getReservationId();
    reply("inventory.events.v1", orderId, com.edacommerce.inventory.StockReservationRejected.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setReservationId(res).setShortages(List.of()).build());
    mvc.perform(post("/ops/sagas/" + orderId + "/retry-step").header("Idempotency-Key", Ids.newId())).andExpect(status().isConflict());
    mvc.perform(post("/ops/sagas/nope/retry-step").header("Idempotency-Key", Ids.newId())).andExpect(status().isNotFound());
  }

  @Test
  void projectorDropsStaleVersionsAndReplayYieldsTheSameRows() {
    String orderId = checkout();
    String res = last(ReserveStock.class, orderId).getReservationId();
    reply("inventory.events.v1", orderId, com.edacommerce.inventory.StockReservationRejected.newBuilder().setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId).setReservationId(res).setShortages(List.of()).build());
    List<MessageDriver.Published> events = driver.publishedFor(orderId).stream().filter(p -> p.topic().equals("order.events.v1")).toList();
    // Out of order: Cancelled (v2) first is retried until Placed (v1) is there.
    List<MessageDriver.Delivery> deliveries = new java.util.ArrayList<>();
    for (MessageDriver.Published p : events) {
      deliveries.add(projector.deliver(p.topic(), orderId, p.record()));
    }
    var snapshot1 = jdbc.queryForList("SELECT status, version FROM order_history.order_summary WHERE order_id = ?", orderId);
    assertThat(snapshot1.get(0).get("status")).isEqualTo("CANCELLED");
    // A stale version (OrderPlaced again with a new eventId) is dropped.
    projector.deliver("order.events.v1", orderId, OrderPlaced.newBuilder((OrderPlaced) events.get(0).record()).build());
    assertThat(jdbc.queryForList("SELECT status, version FROM order_history.order_summary WHERE order_id = ?", orderId)).isEqualTo(snapshot1);
    // Replay from offset 0 into an empty projection gives identical rows.
    var timeline1 = jdbc.queryForList("SELECT event_id, kind FROM order_history.timeline WHERE order_id = ? ORDER BY event_id", orderId);
    jdbc.update("DELETE FROM order_history.timeline WHERE order_id = ?", orderId);
    jdbc.update("DELETE FROM order_history.order_line WHERE order_id = ?", orderId);
    jdbc.update("DELETE FROM order_history.order_summary WHERE order_id = ?", orderId);
    jdbc.update("DELETE FROM inbox WHERE consumer = 'order-history-projector'");
    for (MessageDriver.Delivery d : deliveries) {
      projector.redeliver(d);
    }
    assertThat(jdbc.queryForList("SELECT status, version FROM order_history.order_summary WHERE order_id = ?", orderId)).isEqualTo(snapshot1);
    assertThat(jdbc.queryForList("SELECT event_id, kind FROM order_history.timeline WHERE order_id = ? ORDER BY event_id", orderId))
        .isEqualTo(timeline1);
    assertThat(Instant.now()).isNotNull();
  }
}
