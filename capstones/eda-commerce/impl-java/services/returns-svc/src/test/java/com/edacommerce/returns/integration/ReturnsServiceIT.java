package com.edacommerce.returns.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.common.Address;
import com.edacommerce.common.Envelope;
import com.edacommerce.common.LineItem;
import com.edacommerce.common.Money;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.saga.DeadlineSweeper;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.fulfilment.ExpectReturn;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.InspectionOutcome;
import com.edacommerce.fulfilment.InspectionResult;
import com.edacommerce.fulfilment.ReturnInspected;
import com.edacommerce.fulfilment.ReturnReceived;
import com.edacommerce.inventory.ItemsRestocked;
import com.edacommerce.inventory.RestockItems;
import com.edacommerce.order.OrderConfirmed;
import com.edacommerce.order.OrderDelivered;
import com.edacommerce.order.OrderPlaced;
import com.edacommerce.payment.RefundFailed;
import com.edacommerce.payment.RefundPayment;
import com.edacommerce.payment.RefundSucceeded;
import com.edacommerce.returns.ReturnAuthorized;
import com.edacommerce.returns.ReturnClosed;
import com.edacommerce.returns.ReturnOutcome;
import com.edacommerce.returns.ReturnRefunded;
import com.edacommerce.returns.ReturnRequested;
import com.edacommerce.shipping.IssueReturnLabel;
import com.edacommerce.shipping.ShipmentCreated;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import javax.sql.DataSource;
import org.apache.avro.specific.SpecificRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * returns-svc end to end at the database level: eligibility, the partial refund, the refund retry
 * schedule and the manual decision, expiry, all driven by contract messages and the HTTP API.
 */
@EdaServiceTest
class ReturnsServiceIT {
  static final ObjectMapper JSON = new ObjectMapper();

  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired DeadlineSweeper sweeper;
  MessageDriver driver;
  String orderId;
  String customer;

  /**
   * returns.yaml, with the oneOf rule off: refundAmount is {@code oneOf: [Money, {type: 'null'}]}
   * (OpenAPI 3.1), which the validator matches twice for any value.
   */
  static org.springframework.test.web.servlet.ResultMatcher returnsApi() {
    return OpenApiContract.validResponse("returns.yaml", "validation.response.body.schema.oneOf");
  }

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
    orderId = Ids.newId();
    customer = "cust-" + orderId.substring(24);
  }

  @AfterEach
  void reset() {
    clock.reset();
  }

  /** An order event with a real envelope, so the eligibility view sees its aggregateVersion. */
  <T extends SpecificRecord> T versioned(T record, long version) {
    Envelopes.set(
        record,
        Envelope.newBuilder()
            .setEventId("")
            .setType("")
            .setOccurredAt(Instant.EPOCH)
            .setCorrelationId(orderId)
            .setProducer("order-svc")
            .setPartitionKey(orderId)
            .setAggregateType("Order")
            .setAggregateId(orderId)
            .setAggregateVersion(version)
            .build());
    return record;
  }

  void placed(long unitPriceMinor) {
    Money price = new Money(unitPriceMinor, "EUR");
    Money lineTotal = new Money(unitPriceMinor * 2, "EUR");
    driver.deliver(
        "order.events.v1",
        orderId,
        versioned(
            OrderPlaced.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(orderId)
                .setCustomerId(customer)
                .setLines(
                    List.of(
                        new LineItem("l1", "SKU-1001", "Mug", 2, price, lineTotal),
                        new LineItem("l2", "SKU-1002", "Plate", 1, price, price)))
                .setTotal(new Money(unitPriceMinor * 3 + 499, "EUR"))
                .setShippingAddress(
                    Address.newBuilder()
                        .setRecipientName("Ada Lovelace")
                        .setLine1("Main St 1")
                        .setCity("Berlin")
                        .setPostalCode("10115")
                        .setCountryCode("DE")
                        .build())
                .setContactEmail("ada@example.com")
                .setShippingMethod(ShippingMethod.STANDARD)
                .setPlacedAt(clock.instant())
                .build(),
            1));
  }

  void confirmed() {
    driver.deliver(
        "order.events.v1",
        orderId,
        versioned(
            OrderConfirmed.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(orderId)
                .setReservationId("res")
                .setPaymentId("pay-" + orderId)
                .setFulfilmentId("ful")
                .setConfirmedAt(clock.instant())
                .build(),
            2));
    driver.deliver(
        "fulfilment.events.v1",
        orderId,
        FulfilmentAccepted.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setFulfilmentId("ful")
            .setWarehouseId("wh-berlin-1")
            .setAcceptedAt(clock.instant())
            .setEstimatedDispatchAt(null)
            .build());
  }

  void delivered(long version) {
    driver.deliver(
        "order.events.v1",
        orderId,
        versioned(
            OrderDelivered.newBuilder()
                .setEnvelope(Envelopes.placeholder())
                .setOrderId(orderId)
                .setShipmentId("s")
                .setDeliveredAt(clock.instant())
                .setReturnWindowEndsAt(clock.instant().plus(Duration.ofDays(30)))
                .build(),
            version));
  }

  void deliveredOrder(long unitPriceMinor) {
    placed(unitPriceMinor);
    confirmed();
    delivered(6);
  }

  ResultActions postReturn(String body, String key, String who) throws Exception {
    return mvc.perform(
        post("/returns")
            .contentType(MediaType.APPLICATION_JSON)
            .header("Idempotency-Key", key)
            .header("X-Local-Customer-Id", who)
            .content(body));
  }

  String body(int qty, String reason) {
    return "{\"orderId\":\""
        + orderId
        + "\",\"lines\":[{\"lineId\":\"l1\",\"quantity\":"
        + qty
        + "}],\"reason\":\""
        + reason
        + "\"}";
  }

  String requestReturn(int qty, String reason) throws Exception {
    String json =
        postReturn(body(qty, reason), Ids.newId(), customer)
            .andExpect(status().isAccepted())
            .andExpect(returnsApi())
            .andReturn()
            .getResponse()
            .getContentAsString();
    return JSON.readTree(json).get("returnId").asText();
  }

  JsonNode getReturn(String returnId) throws Exception {
    return JSON.readTree(
        mvc.perform(get("/returns/" + returnId).header("X-Local-Customer-Id", customer))
            .andExpect(status().isOk())
            .andExpect(returnsApi())
            .andReturn()
            .getResponse()
            .getContentAsString());
  }

  ResultActions decide(String returnId, String decision) throws Exception {
    return mvc.perform(
        post("/ops/returns/" + returnId + "/decision")
            .contentType(MediaType.APPLICATION_JSON)
            .header("Idempotency-Key", Ids.newId())
            .content("{\"decision\":\"" + decision + "\",\"note\":\"checked\"}"));
  }

  void deliverToReturn(String returnId, SpecificRecord record, String topic) {
    driver.deliver(topic, orderId, record, returnId, null);
  }

  void received(String returnId) {
    deliverToReturn(
        returnId,
        ReturnReceived.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setReturnId(returnId)
            .setReceivedAt(clock.instant())
            .build(),
        "fulfilment.events.v1");
  }

  MessageDriver.Delivery inspected(String returnId, InspectionResult... results) {
    return driver.deliver(
        "fulfilment.events.v1",
        orderId,
        ReturnInspected.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setReturnId(returnId)
            .setResults(List.of(results))
            .setInspectedAt(clock.instant())
            .build(),
        returnId,
        null);
  }

  static InspectionResult result(int q, InspectionOutcome o) {
    return new InspectionResult("l1", "SKU-1001", q, o, null);
  }

  void restocked(String returnId, String restockId) {
    deliverToReturn(
        returnId,
        ItemsRestocked.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setReturnId(returnId)
            .setRestockId(restockId)
            .setLines(List.of())
            .setRestockedAt(clock.instant())
            .build(),
        "inventory.events.v1");
  }

  void refunded(String returnId, RefundPayment cmd) {
    deliverToReturn(
        returnId,
        RefundSucceeded.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setPaymentId(cmd.getPaymentId())
            .setRefundId(cmd.getRefundId())
            .setReturnId(returnId)
            .setAmount(cmd.getAmount())
            .setPspReference("psp-1")
            .setRefundedAt(clock.instant())
            .build(),
        "payment.events.v1");
  }

  void refundFailed(String returnId, RefundPayment cmd, boolean retryable) {
    deliverToReturn(
        returnId,
        RefundFailed.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setPaymentId(cmd.getPaymentId())
            .setRefundId(cmd.getRefundId())
            .setReturnId(returnId)
            .setReason("processing_error")
            .setRetryable(retryable)
            .setFailedAt(clock.instant())
            .build(),
        "payment.events.v1");
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void aReturnWithOneDamagedItemEndsPartiallyRefunded() throws Exception {
    deliveredOrder(12_999);
    String key = Ids.newId();
    String first =
        postReturn(body(2, "CHANGED_MIND"), key, customer)
            .andExpect(status().isAccepted())
            .andExpect(header().exists("Location"))
            .andExpect(jsonPath("$.status").value("AWAITING_PARCEL"))
            .andExpect(jsonPath("$.rmaNumber").value(org.hamcrest.Matchers.startsWith("RMA-")))
            .andExpect(returnsApi())
            .andReturn()
            .getResponse()
            .getContentAsString();
    postReturn(body(2, "CHANGED_MIND"), key, customer)
        .andExpect(status().isAccepted())
        .andExpect(header().string("Idempotent-Replayed", "true"))
        .andExpect(
            org.springframework.test.web.servlet.result.MockMvcResultMatchers.content()
                .json(first));
    String returnId = JSON.readTree(first).get("returnId").asText();

    ReturnRequested requested = driver.published(ReturnRequested.class, orderId).get(0);
    assertThat(requested.getEnvelope().getCorrelationId()).isEqualTo(returnId);
    assertThat(requested.getEnvelope().getAggregateVersion()).isEqualTo(1L);
    assertThat(
            driver
                .published(ReturnAuthorized.class, orderId)
                .get(0)
                .getEnvelope()
                .getAggregateVersion())
        .isEqualTo(2L);
    IssueReturnLabel label = driver.published(IssueReturnLabel.class, orderId).get(0);
    assertThat(label.getToWarehouseId()).isEqualTo("wh-berlin-1");
    assertThat(label.getPickupFrom().getCity()).isEqualTo("Berlin");
    ExpectReturn expect = driver.published(ExpectReturn.class, orderId).get(0);
    assertThat(expect.getRmaNumber()).isEqualTo(JSON.readTree(first).get("rmaNumber").asText());

    mvc.perform(get("/returns/" + returnId + "/label").header("X-Local-Customer-Id", customer))
        .andExpect(status().isNotFound())
        .andExpect(returnsApi());
    deliverToReturn(
        returnId,
        ShipmentCreated.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setShipmentId(label.getShipmentId())
            .setDirection(ShipmentDirection.RETURN)
            .setFulfilmentId(null)
            .setReturnId(returnId)
            .setCarrier("fake-carrier")
            .setTrackingNumber("FC1")
            .setLabel(
                ClaimChecks.of(
                    "shipping-labels", "shipping/l.pdf", new byte[] {1}, "application/pdf", null))
            .setCreatedAt(clock.instant())
            .build(),
        "shipping.events.v1");
    assertThat(getReturn(returnId).get("labelAvailable").asBoolean()).isTrue();
    mvc.perform(get("/returns/" + returnId + "/label").header("X-Local-Customer-Id", customer))
        .andExpect(status().isFound())
        .andExpect(
            header().string("Location", org.hamcrest.Matchers.containsString("shipping/l.pdf")))
        .andExpect(returnsApi());

    received(returnId);
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("RECEIVED");
    MessageDriver.Delivery insp =
        inspected(
            returnId,
            result(1, InspectionOutcome.RESTOCKABLE),
            result(1, InspectionOutcome.DAMAGED));
    assertThat(driver.redeliver(insp).outcome()).isEqualTo(Outcome.DUPLICATE);
    JsonNode refunding = getReturn(returnId);
    assertThat(refunding.get("status").asText()).isEqualTo("REFUNDING");
    assertThat(refunding.get("refundAmount").get("amountMinor").asLong()).isEqualTo(12_999);
    assertThat(refunding.get("lines")).hasSize(2);

    RestockItems restock = driver.published(RestockItems.class, orderId).get(0);
    assertThat(restock.getLines()).hasSize(1);
    assertThat(restock.getLines().get(0).getQuantity()).isEqualTo(1);
    List<RefundPayment> refunds = driver.published(RefundPayment.class, orderId);
    assertThat(refunds).hasSize(1);
    RefundPayment refund = refunds.get(0);
    assertThat(refund.getPaymentId()).isEqualTo("pay-" + orderId);
    assertThat(refund.getReturnId()).isEqualTo(returnId);
    assertThat(refund.getAmount().getAmountMinor()).isEqualTo(12_999);

    restocked(returnId, restock.getRestockId());
    refunded(returnId, refund);
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("PARTIALLY_REFUNDED");
    assertThat(driver.published(ReturnRefunded.class, orderId)).hasSize(1);
    ReturnClosed closed = driver.published(ReturnClosed.class, orderId).get(0);
    assertThat(closed.getOutcome()).isEqualTo(ReturnOutcome.PARTIALLY_REFUNDED);

    mvc.perform(get("/orders/" + orderId + "/returns").header("X-Local-Customer-Id", customer))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.returns.length()").value(1))
        .andExpect(jsonPath("$.returnable.length()").value(1))
        .andExpect(jsonPath("$.returnable[0].lineId").value("l2"))
        .andExpect(returnsApi());
    mvc.perform(get("/ops/sagas/" + returnId))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.sagaType").value("RETURN"))
        .andExpect(jsonPath("$.state").value("CLOSED"))
        .andExpect(jsonPath("$.history[1].to").value("AUTHORIZED"))
        .andExpect(OpenApiContract.validResponse("admin.yaml"));
  }

  @Test
  void ineligibleReturnsAreRefusedWithAReason() throws Exception {
    placed(1000);
    confirmed();
    postReturn(body(1, "OTHER"), Ids.newId(), customer)
        .andExpect(status().isUnprocessableEntity())
        .andExpect(
            jsonPath("$.type").value("https://errors.edacommerce.example/return-not-delivered"))
        .andExpect(returnsApi());
    delivered(6);
    postReturn(body(3, "OTHER"), Ids.newId(), customer)
        .andExpect(status().isUnprocessableEntity())
        .andExpect(
            jsonPath("$.type")
                .value("https://errors.edacommerce.example/return-quantity-exceeded"));
    postReturn(body(1, "OTHER"), Ids.newId(), "someone-else")
        .andExpect(status().isNotFound())
        .andExpect(returnsApi());
    postReturn(body(1, "BORED"), Ids.newId(), customer).andExpect(status().isBadRequest());
    postReturn(
            "{\"orderId\":\"" + orderId + "\",\"lines\":[],\"reason\":\"OTHER\"}",
            Ids.newId(),
            customer)
        .andExpect(status().isBadRequest())
        .andExpect(returnsApi());
    clock.advance(Duration.ofDays(31));
    postReturn(body(1, "OTHER"), Ids.newId(), customer)
        .andExpect(status().isUnprocessableEntity())
        .andExpect(
            jsonPath("$.type").value("https://errors.edacommerce.example/return-window-closed"));
  }

  @Test
  void aHighValueReturnWaitsForTheOpsDecision() throws Exception {
    deliveredOrder(30_000);
    String returnId = requestReturn(2, "CHANGED_MIND");
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("MANUAL_REVIEW");
    assertThat(driver.published(IssueReturnLabel.class, orderId)).isEmpty();
    decide(returnId, "RETRY_REFUND").andExpect(status().isConflict()).andExpect(returnsApi());
    decide(returnId, "APPROVE")
        .andExpect(status().isAccepted())
        .andExpect(jsonPath("$.status").value("AWAITING_PARCEL"))
        .andExpect(returnsApi());
    assertThat(driver.published(IssueReturnLabel.class, orderId)).hasSize(1);
    decide(Ids.newId(), "APPROVE").andExpect(status().isNotFound());
  }

  @Test
  void refundsAreRetriedOnTheScheduleThenDecidedByAHuman() throws Exception {
    deliveredOrder(12_999);
    String returnId = requestReturn(1, "CHANGED_MIND");
    received(returnId);
    inspected(returnId, result(1, InspectionOutcome.RESTOCKABLE));
    restocked(returnId, driver.published(RestockItems.class, orderId).get(0).getRestockId());
    RefundPayment refund = driver.published(RefundPayment.class, orderId).get(0);
    for (Duration wait :
        List.of(Duration.ofMinutes(1), Duration.ofMinutes(10), Duration.ofHours(1))) {
      refundFailed(returnId, refund, true);
      clock.advance(wait.minusSeconds(5));
      sweeper.sweepOnce();
      int before = driver.published(RefundPayment.class, orderId).size();
      clock.advance(Duration.ofSeconds(10));
      sweeper.sweepOnce();
      assertThat(driver.published(RefundPayment.class, orderId)).hasSize(before + 1);
    }
    List<RefundPayment> all = driver.published(RefundPayment.class, orderId);
    assertThat(all).hasSize(4);
    assertThat(all).allSatisfy(r -> assertThat(r.getRefundId()).isEqualTo(refund.getRefundId()));
    refundFailed(returnId, refund, true);
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("MANUAL_REVIEW");

    decide(returnId, "RETRY_REFUND").andExpect(status().isAccepted());
    assertThat(driver.published(RefundPayment.class, orderId)).hasSize(5);
    refunded(returnId, refund);
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("REFUNDED");
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM saga_transition WHERE saga_id = ? AND to_state = 'REFUND_REVIEW'",
                Integer.class,
                returnId))
        .isEqualTo(1);
  }

  @Test
  void anUnsentParcelExpiresAndFreesTheQuantity() throws Exception {
    deliveredOrder(1_000);
    String returnId = requestReturn(2, "OTHER");
    postReturn(body(1, "OTHER"), Ids.newId(), customer).andExpect(status().isUnprocessableEntity());
    clock.advance(Duration.ofDays(15));
    sweeper.sweepOnce();
    assertThat(getReturn(returnId).get("status").asText()).isEqualTo("EXPIRED");
    assertThat(driver.published(ReturnClosed.class, orderId).get(0).getOutcome())
        .isEqualTo(ReturnOutcome.EXPIRED);
    clock.reset();
    clock.advance(Duration.ofDays(1));
    requestReturn(2, "OTHER");
  }

  @Test
  void theViewKeepsLateFactsAndNeverMovesBackwards() throws Exception {
    placed(1_000);
    delivered(6); // overtakes OrderConfirmed (v2) through a retry topic
    confirmed();
    assertThat(
            jdbc.queryForObject(
                "SELECT status || '/' || payment_id FROM eligibility_view WHERE order_id = ?",
                String.class,
                orderId))
        .isEqualTo("DELIVERED/pay-" + orderId);
    requestReturn(1, "OTHER");
  }
}
