package com.edacommerce.fulfilment.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.common.Address;
import com.edacommerce.common.ClaimCheck;
import com.edacommerce.common.LineItem;
import com.edacommerce.common.Money;
import com.edacommerce.common.ReturnLine;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.InMemoryClaimCheckStore;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.fulfilment.CancelFulfilment;
import com.edacommerce.fulfilment.ExpectReturn;
import com.edacommerce.fulfilment.FulfilmentAccepted;
import com.edacommerce.fulfilment.FulfilmentCancelled;
import com.edacommerce.fulfilment.FulfilmentFailed;
import com.edacommerce.fulfilment.FulfilmentFailureReason;
import com.edacommerce.fulfilment.InspectionOutcome;
import com.edacommerce.fulfilment.OrderDispatched;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.fulfilment.OrderPicked;
import com.edacommerce.fulfilment.RequestFulfilment;
import com.edacommerce.fulfilment.ReturnInspected;
import com.edacommerce.fulfilment.ReturnReceived;
import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWms;
import com.edacommerce.fulfilment.adapters.out.wms.fake.FakeWmsConfig;
import com.edacommerce.fulfilment.application.FulfilmentUseCases;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import javax.sql.DataSource;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.ApplicationContext;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/**
 * Layer 3 for fulfilment-svc: real Spring context, Flyway, PostgreSQL; commands and events driven
 * through the real consumer runtime, the fake WMS ticked on the test clock.
 */
@EdaServiceTest
@TestPropertySource(
    properties = {
      "fulfilment.fake-wms.drop-request-rate=0",
      "fulfilment.fake-wms.accept-delay-ms=1000",
      "fulfilment.fake-wms.pick-delay-ms=1000",
      "fulfilment.fake-wms.pack-delay-ms=1000",
      "fulfilment.fake-wms.fail-rate=0",
      "fulfilment.fake-wms.inspection-damaged-rate=0"
    })
class FulfilmentServiceIT {
  static final FakeWmsConfig QUIET = new FakeWmsConfig(0.0, 1000, 1000, 1000, 0.0, 2000, 0.0);

  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired FakeWms wms;
  @Autowired FulfilmentUseCases useCases;
  @Autowired InMemoryClaimCheckStore documents;
  MessageDriver driver;

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
  }

  @AfterEach
  void reset() {
    clock.reset();
    wms.update(QUIET);
  }

  static RequestFulfilment request(String orderId, String fulfilmentId, int attempt) {
    Money price = new Money(1299L, "EUR");
    return RequestFulfilment.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setFulfilmentId(fulfilmentId)
        .setLines(
            List.of(
                new LineItem("l1", "SKU-1001", "Mug", 2, price, new Money(2598L, "EUR")),
                new LineItem("l2", "SKU-1002", "Plate", 1, price, price)))
        .setShipTo(
            Address.newBuilder()
                .setRecipientName("Ada Lovelace")
                .setLine1("Main St 1")
                .setCity("Berlin")
                .setPostalCode("10115")
                .setCountryCode("DE")
                .build())
        .setShippingMethod(ShippingMethod.STANDARD)
        .setAttempt(attempt)
        .build();
  }

  MessageDriver.Delivery deliverRequest(String orderId, String fulfilmentId, int attempt) {
    return driver.deliver(
        "fulfilment.commands.v1", orderId, request(orderId, fulfilmentId, attempt));
  }

  /** Moves the clock and lets the fake warehouse report everything that became due. */
  void warehouseWorks(int steps) {
    for (int i = 0; i < steps; i++) {
      clock.advance(Duration.ofSeconds(1));
      wms.tick(useCases);
    }
  }

  ShipmentCreated outboundShipment(String orderId, String fulfilmentId, String shipmentId) {
    return ShipmentCreated.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setShipmentId(shipmentId)
        .setDirection(ShipmentDirection.OUTBOUND)
        .setFulfilmentId(fulfilmentId)
        .setReturnId(null)
        .setCarrier("fake-carrier")
        .setTrackingNumber("FC000000000001")
        .setLabel(
            ClaimChecks.of(
                "shipping-labels", "shipping/x.pdf", new byte[] {1}, "application/pdf", null))
        .setCreatedAt(clock.instant())
        .build();
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void happyPathAcceptsPicksPacksWithAManifestClaimCheckAndDispatches() {
    String orderId = Ids.newId();
    String fulfilmentId = Ids.newId();
    MessageDriver.Delivery d = deliverRequest(orderId, fulfilmentId, 1);
    assertThat(d.outcome()).isEqualTo(Outcome.SUCCESS);
    assertThat(driver.publishedFor(orderId)).as("the warehouse has not answered yet").isEmpty();

    warehouseWorks(3);
    List<MessageDriver.Published> events = driver.publishedFor(orderId);
    assertThat(events)
        .extracting(MessageDriver.Published::type)
        .containsExactly(
            "com.edacommerce.fulfilment.FulfilmentAccepted",
            "com.edacommerce.fulfilment.OrderPicked",
            "com.edacommerce.fulfilment.OrderPacked");
    assertThat(events)
        .extracting(p -> p.envelope().getAggregateVersion())
        .containsExactly(1L, 2L, 3L);
    assertThat(events.get(0).envelope().getProducer()).isEqualTo("fulfilment-svc");
    assertThat(events.get(0).envelope().getPartitionKey()).isEqualTo(orderId);
    assertThat(events.get(0).envelope().getCorrelationId()).isEqualTo(orderId);
    FulfilmentAccepted accepted = (FulfilmentAccepted) events.get(0).record();
    assertThat(accepted.getWarehouseId()).isEqualTo(FakeWms.WAREHOUSE_ID);
    assertThat(events.get(1).record()).isInstanceOf(OrderPicked.class);

    OrderPacked packed = (OrderPacked) events.get(2).record();
    ClaimCheck manifest = packed.getManifest();
    assertThat(manifest.getBucket()).isEqualTo("packing-manifests");
    assertThat(manifest.getObjectKey())
        .startsWith("fulfilment/")
        .endsWith("/" + orderId + "/" + fulfilmentId + ".json");
    assertThat(manifest.getSizeBytes()).as("2,000 scans").isGreaterThan(256_000);
    assertThat(manifest.getExpiresAt()).isNotNull();
    // A consumer downloads the manifest and verifies size and SHA-256.
    byte[] downloaded = documents.get(manifest);
    assertThat(ClaimChecks.sha256(downloaded)).isEqualTo(manifest.getSha256());
    Integer payloadBytes =
        jdbc.queryForObject(
            "SELECT length(payload) FROM outbox WHERE aggregate_id = ? AND event_type = ?",
            Integer.class,
            orderId,
            "com.edacommerce.fulfilment.OrderPacked");
    assertThat(payloadBytes).as("OrderPacked stays small (claim check)").isLessThan(2048);
    assertThat(packed.getParcels()).hasSize(1);
    assertThat(packed.getShipTo().getCity()).isEqualTo("Berlin");

    MessageDriver.Delivery shipment =
        driver.deliver(
            "shipping.events.v1", orderId, outboundShipment(orderId, fulfilmentId, "s-" + orderId));
    List<OrderDispatched> dispatched = driver.published(OrderDispatched.class, orderId);
    assertThat(dispatched).hasSize(1);
    assertThat(dispatched.get(0).getShipmentId()).isEqualTo("s-" + orderId);
    assertThat(dispatched.get(0).getEnvelope().getCausationId()).isEqualTo(shipment.eventId());
    assertThat(dispatched.get(0).getEnvelope().getAggregateVersion()).isEqualTo(4L);

    driver.deliver(
        "shipping.events.v1", orderId, outboundShipment(orderId, fulfilmentId, "s-" + orderId));
    assertThat(driver.published(OrderDispatched.class, orderId))
        .as("a re-emitted ShipmentCreated changes nothing")
        .hasSize(1);
  }

  @Test
  void aDroppedRequestIsRecoveredByTheResendWithoutASecondPickOrder() {
    String orderId = Ids.newId();
    String fulfilmentId = Ids.newId();
    wms.update(new FakeWmsConfig(1.0, null, null, null, null, null, null));
    deliverRequest(orderId, fulfilmentId, 1);
    warehouseWorks(3);
    assertThat(driver.publishedFor(orderId)).as("the warehouse lost it").isEmpty();
    assertThat(wms.pickOrders(fulfilmentId)).isZero();

    wms.update(new FakeWmsConfig(0.0, null, null, null, null, null, null));
    deliverRequest(orderId, fulfilmentId, 2); // the saga's deadline resend: new eventId
    deliverRequest(orderId, fulfilmentId, 3); // a second resend before the warehouse answered
    warehouseWorks(1);
    assertThat(driver.published(FulfilmentAccepted.class, orderId)).hasSize(1);
    assertThat(wms.pickOrders(fulfilmentId)).isEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "SELECT attempt FROM fulfilment WHERE fulfilment_id = ?",
                Integer.class,
                fulfilmentId))
        .isEqualTo(3);

    deliverRequest(orderId, fulfilmentId, 4); // a resend after the ack: the original reply
    List<FulfilmentAccepted> replies = driver.published(FulfilmentAccepted.class, orderId);
    assertThat(replies).hasSize(2);
    assertThat(replies.get(1).getAcceptedAt()).isEqualTo(replies.get(0).getAcceptedAt());
    assertThat(replies.get(1).getEnvelope().getAggregateVersion()).isEqualTo(1L);
    assertThat(wms.pickOrders(fulfilmentId)).isEqualTo(1);
  }

  @Test
  void theSameMessageTwiceIsADuplicate() {
    String orderId = Ids.newId();
    String fulfilmentId = Ids.newId();
    MessageDriver.Delivery d = deliverRequest(orderId, fulfilmentId, 1);
    assertThat(driver.redeliver(d).outcome()).isEqualTo(Outcome.DUPLICATE);
    warehouseWorks(1);
    assertThat(driver.published(FulfilmentAccepted.class, orderId)).hasSize(1);
    assertThat(wms.pickOrders(fulfilmentId)).isEqualTo(1);
  }

  @Test
  void cancelStopsTheWarehouseAndATombstoneBlocksALateRequest() {
    String orderId = Ids.newId();
    String fulfilmentId = Ids.newId();
    deliverRequest(orderId, fulfilmentId, 1);
    warehouseWorks(1);
    driver.deliver(
        "fulfilment.commands.v1",
        orderId,
        CancelFulfilment.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setFulfilmentId(fulfilmentId)
            .setReason("PAYMENT_DECLINED")
            .build());
    warehouseWorks(3);
    assertThat(driver.publishedFor(orderId))
        .extracting(MessageDriver.Published::type)
        .containsExactly(
            "com.edacommerce.fulfilment.FulfilmentAccepted",
            "com.edacommerce.fulfilment.FulfilmentCancelled");

    String other = Ids.newId();
    driver.deliver(
        "fulfilment.commands.v1",
        orderId,
        CancelFulfilment.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setFulfilmentId(other)
            .setReason("SAGA_TIMEOUT")
            .build());
    deliverRequest(orderId, other, 1); // arrives late through a retry topic
    warehouseWorks(3);
    assertThat(wms.pickOrders(other)).isZero();
    assertThat(driver.published(FulfilmentCancelled.class, orderId)).hasSize(3);
  }

  @Test
  void aWarehouseFailureIsReported() {
    String orderId = Ids.newId();
    wms.update(new FakeWmsConfig(null, null, null, null, 1.0, null, null));
    deliverRequest(orderId, Ids.newId(), 1);
    warehouseWorks(3);
    List<FulfilmentFailed> failed = driver.published(FulfilmentFailed.class, orderId);
    assertThat(failed).hasSize(1);
    assertThat(failed.get(0).getReason()).isEqualTo(FulfilmentFailureReason.STOCK_DAMAGED);
    assertThat(driver.published(OrderPacked.class, orderId)).isEmpty();
  }

  @Test
  void aReturnParcelIsReceivedAndInspected() {
    String orderId = Ids.newId();
    String returnId = Ids.newId();
    ShipmentDelivered delivered =
        ShipmentDelivered.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setShipmentId(Ids.newId())
            .setDirection(ShipmentDirection.RETURN)
            .setReturnId(returnId)
            .setCarrierEventId("ce-1")
            .setDeliveredAt(clock.instant())
            .build();
    assertThatThrownBy(() -> driver.deliver("shipping.events.v1", orderId, delivered))
        .as("ExpectReturn not processed yet: try again later (retry topic)")
        .isInstanceOf(RetryLaterException.class);

    driver.deliver(
        "fulfilment.commands.v1",
        orderId,
        ExpectReturn.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setReturnId(returnId)
            .setRmaNumber("RMA-2026-000042")
            .setLines(List.of(new ReturnLine("l1", "SKU-1001", 2)))
            .setExpectedBy(Instant.now().plus(Duration.ofDays(14)))
            .build(),
        returnId,
        null);
    wms.update(new FakeWmsConfig(null, null, null, null, null, null, 1.0));
    driver.deliver("shipping.events.v1", orderId, delivered, returnId, null);
    driver.deliver("shipping.events.v1", orderId, delivered, returnId, null);
    assertThat(driver.published(ReturnReceived.class, orderId)).hasSize(1);

    warehouseWorks(2);
    List<ReturnInspected> inspected = driver.published(ReturnInspected.class, orderId);
    assertThat(inspected).hasSize(1);
    assertThat(inspected.get(0).getResults()).hasSize(1);
    assertThat(inspected.get(0).getResults().get(0).getOutcome())
        .isEqualTo(InspectionOutcome.DAMAGED);
    assertThat(inspected.get(0).getResults().get(0).getQuantity()).isEqualTo(2);
    assertThat(inspected.get(0).getEnvelope().getCorrelationId()).isEqualTo(returnId);
  }

  @Test
  void theFakeWarehouseIsConfiguredThroughTheAdminApi() throws Exception {
    mvc.perform(
            put("/admin/fakes/wms")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"dropRequestRate\": 0.5, \"acceptDelayMs\": 10}"))
        .andExpect(status().isOk())
        .andExpect(OpenApiContract.validResponse("admin.yaml"));
    assertThat(wms.config().dropRequestRate()).isEqualTo(0.5);
    assertThat(wms.config().acceptDelayMs()).isEqualTo(10);
    assertThat(wms.config().manifestLines()).isEqualTo(2000);
  }
}
