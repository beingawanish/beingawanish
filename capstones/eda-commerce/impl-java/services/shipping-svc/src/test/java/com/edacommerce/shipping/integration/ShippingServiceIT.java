package com.edacommerce.shipping.integration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.edacommerce.common.Address;
import com.edacommerce.common.ShipmentDirection;
import com.edacommerce.common.ShippingMethod;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.testing.EdaServiceTest;
import com.edacommerce.edacommon.testing.InMemoryClaimCheckStore;
import com.edacommerce.edacommon.testing.MessageDriver;
import com.edacommerce.edacommon.testing.MutableClock;
import com.edacommerce.edacommon.testing.OpenApiContract;
import com.edacommerce.edacommon.testing.SharedTables;
import com.edacommerce.edacommon.webhooks.WebhookVerifier;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.fulfilment.Parcel;
import com.edacommerce.shipping.IssueReturnLabel;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import com.edacommerce.shipping.ShipmentException;
import com.edacommerce.shipping.ShipmentExceptionCode;
import com.edacommerce.shipping.ShipmentInTransit;
import com.edacommerce.shipping.adapters.out.carrier.fake.CarrierWebhookTransport;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrier;
import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrierConfig;
import com.edacommerce.shipping.application.ShippingUseCases;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
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
import org.springframework.context.annotation.Primary;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

/**
 * shipping-svc checklist: out-of-order and duplicate carrier webhooks yield monotonic, unique
 * events; labels by claim check; booking retries; signature checks.
 */
@EdaServiceTest
@Import(ShippingServiceIT.Webhooks.class)
@TestPropertySource(
    properties = {
      "shipping.fake-carrier.duplicate-rate=0",
      "shipping.fake-carrier.out-of-order-rate=0",
      "shipping.fake-carrier.exception-rate=0",
      "shipping.fake-carrier.step-delay-ms=1000",
      "shipping.fake-carrier.booking-failure-rate=0"
    })
class ShippingServiceIT {
  static final FakeCarrierConfig QUIET = new FakeCarrierConfig(0.0, 0.0, 0.0, 1000, 0.0);
  static final ObjectMapper JSON = new ObjectMapper();

  /** One captured webhook. */
  @SuppressWarnings("ArrayRecordComponent")
  record Sent(byte[] body, long ts, String signature) {
    JsonNode json() {
      try {
        return JSON.readTree(body);
      } catch (java.io.IOException e) {
        throw new IllegalStateException(e);
      }
    }
  }

  static final List<Sent> SENT = new CopyOnWriteArrayList<>();

  @TestConfiguration
  static class Webhooks {
    @Bean
    @Primary
    CarrierWebhookTransport capturingTransport() {
      return (body, ts, sig) -> SENT.add(new Sent(body, ts, sig));
    }
  }

  @Autowired ApplicationContext ctx;
  @Autowired MockMvc mvc;
  @Autowired JdbcTemplate jdbc;
  @Autowired DataSource dataSource;
  @Autowired MutableClock clock;
  @Autowired FakeCarrier carrier;
  @Autowired ShippingUseCases useCases;
  @Autowired WebhookVerifier verifier;
  @Autowired InMemoryClaimCheckStore documents;
  MessageDriver driver;

  @BeforeEach
  void setUp() {
    driver = new MessageDriver(ctx);
    SENT.clear();
  }

  @AfterEach
  void reset() {
    clock.reset();
    carrier.update(QUIET);
  }

  static Address address() {
    return Address.newBuilder()
        .setRecipientName("Ada Lovelace")
        .setLine1("Main St 1")
        .setCity("Berlin")
        .setPostalCode("10115")
        .setCountryCode("DE")
        .build();
  }

  OrderPacked packed(String orderId, String fulfilmentId) {
    return OrderPacked.newBuilder()
        .setEnvelope(Envelopes.placeholder())
        .setOrderId(orderId)
        .setFulfilmentId(fulfilmentId)
        .setWarehouseId("wh-berlin-1")
        .setParcels(List.of(new Parcel("p1", 900, 400, 300, 150)))
        .setManifest(
            ClaimChecks.of("packing-manifests", "m.json", new byte[] {1}, "application/json", null))
        .setShipTo(address())
        .setShippingMethod(ShippingMethod.EXPRESS)
        .setPackedAt(clock.instant())
        .build();
  }

  ShipmentCreated book(String orderId) {
    driver.deliver("fulfilment.events.v1", orderId, packed(orderId, "f-" + orderId));
    List<ShipmentCreated> created = driver.published(ShipmentCreated.class, orderId);
    assertThat(created).hasSize(1);
    return created.get(0);
  }

  ResultActions postWebhook(byte[] body, long ts, String signature) throws Exception {
    return mvc.perform(
        post("/webhooks/carrier")
            .contentType(MediaType.APPLICATION_JSON)
            .content(body)
            .header("X-Webhook-Timestamp", Long.toString(ts))
            .header("X-Carrier-Signature", signature));
  }

  /** Lets the fake carrier send everything planned (clock moved past the last step). */
  List<Sent> carrierSendsAll(String trackingNumber) {
    clock.advance(Duration.ofSeconds(30));
    carrier.tick();
    List<Sent> out = new ArrayList<>();
    for (Sent s : SENT) {
      if (s.json().get("trackingNumber").asText().equals(trackingNumber)) {
        out.add(s);
      }
    }
    SENT.clear();
    return out;
  }

  @Test
  void sharedTablesMatchTheContract() {
    SharedTables.assertMatchesContract(dataSource);
  }

  @Test
  void orderPackedBooksTheCarrierAndPublishesShipmentCreatedWithALabelClaimCheck() {
    String orderId = Ids.newId();
    MessageDriver.Delivery d =
        driver.deliver("fulfilment.events.v1", orderId, packed(orderId, "f-" + orderId));
    ShipmentCreated created = driver.published(ShipmentCreated.class, orderId).get(0);
    assertThat(created.getDirection()).isEqualTo(ShipmentDirection.OUTBOUND);
    assertThat(created.getFulfilmentId()).isEqualTo("f-" + orderId);
    assertThat(created.getCarrier()).isEqualTo("fake-carrier");
    assertThat(created.getTrackingNumber())
        .isEqualTo(FakeCarrier.trackingNumberFor(created.getShipmentId()));
    assertThat(created.getEnvelope().getCausationId()).isEqualTo(d.eventId());
    assertThat(created.getEnvelope().getProducer()).isEqualTo("shipping-svc");
    assertThat(created.getEnvelope().getAggregateType()).isEqualTo("Shipment");
    assertThat(created.getLabel().getBucket()).isEqualTo("shipping-labels");
    assertThat(created.getLabel().getObjectKey())
        .startsWith("shipping/")
        .endsWith("/" + orderId + "/" + created.getShipmentId() + ".pdf");
    byte[] pdf = documents.get(created.getLabel());
    assertThat(new String(pdf, 0, 5, StandardCharsets.US_ASCII)).isEqualTo("%PDF-");

    driver.deliver("fulfilment.events.v1", orderId, packed(orderId, "f-" + orderId));
    List<ShipmentCreated> again = driver.published(ShipmentCreated.class, orderId);
    assertThat(again).hasSize(2);
    assertThat(again.get(1).getShipmentId()).isEqualTo(created.getShipmentId());
    assertThat(again.get(1).getEnvelope().getAggregateVersion()).isEqualTo(1L);
    assertThat(carrier.bookings(created.getShipmentId())).isEqualTo(1);
  }

  @Test
  void anUnavailableCarrierIsRetriedWithBackoffThenGivenUp() {
    String orderId = Ids.newId();
    carrier.update(new FakeCarrierConfig(null, null, null, null, 1.0));
    assertThat(
            driver
                .deliver("fulfilment.events.v1", orderId, packed(orderId, "f-" + orderId))
                .outcome())
        .isEqualTo(Outcome.SUCCESS);
    assertThat(driver.publishedFor(orderId)).isEmpty();
    assertThat(useCases.retryDueBookings(10)).as("not due before 10 s").isZero();
    clock.advance(Duration.ofSeconds(11));
    assertThat(useCases.retryDueBookings(10)).isEqualTo(1);
    assertThat(driver.publishedFor(orderId)).isEmpty();

    carrier.update(new FakeCarrierConfig(null, null, null, null, 0.0));
    clock.advance(Duration.ofMinutes(2));
    useCases.retryDueBookings(10);
    List<ShipmentCreated> created = driver.published(ShipmentCreated.class, orderId);
    assertThat(created).hasSize(1);

    String other = Ids.newId();
    carrier.update(new FakeCarrierConfig(null, null, null, null, 1.0));
    driver.deliver("fulfilment.events.v1", other, packed(other, "f-" + other));
    for (int i = 0; i < 5; i++) {
      clock.advance(Duration.ofHours(2));
      useCases.retryDueBookings(10);
    }
    List<ShipmentException> failed = driver.published(ShipmentException.class, other);
    assertThat(failed).hasSize(1);
    assertThat(failed.get(0).getCode()).isEqualTo(ShipmentExceptionCode.BOOKING_FAILED);
    assertThat(
            jdbc.queryForObject(
                "SELECT status FROM shipment WHERE order_id = ?", String.class, other))
        .isEqualTo("BOOKING_FAILED");
  }

  @Test
  void duplicatedAndReorderedWebhooksYieldMonotonicUniqueEvents() throws Exception {
    String orderId = Ids.newId();
    carrier.update(new FakeCarrierConfig(1.0, 1.0, null, null, null));
    ShipmentCreated created = book(orderId);
    List<Sent> sent = carrierSendsAll(created.getTrackingNumber());
    assertThat(sent).as("4 statuses, each sent twice").hasSize(8);

    // Deliver DELIVERED first, then everything (duplicates included) in reverse order.
    Sent delivered =
        sent.stream()
            .filter(s -> s.json().get("status").asText().equals("DELIVERED"))
            .findFirst()
            .orElseThrow();
    postWebhook(delivered.body(), delivered.ts(), delivered.signature()).andExpect(status().isOk());
    useCases.processTracking(100);
    for (int i = sent.size() - 1; i >= 0; i--) {
      Sent s = sent.get(i);
      postWebhook(s.body(), s.ts(), s.signature()).andExpect(status().isOk());
    }
    useCases.processTracking(100);

    assertThat(driver.published(ShipmentDelivered.class, orderId)).hasSize(1);
    assertThat(driver.published(ShipmentInTransit.class, orderId))
        .as("everything else ranks below DELIVERED: stored only")
        .isEmpty();
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM tracking_event WHERE tracking_number = ?",
                Integer.class,
                created.getTrackingNumber()))
        .as("every distinct raw webhook is kept for audit")
        .isEqualTo(4);
    assertThat(
            jdbc.queryForObject(
                "SELECT count(*) FROM inbox WHERE consumer = 'carrier-webhook'"
                    + " AND message_id IN (SELECT carrier_event_id FROM tracking_event WHERE tracking_number = ?)",
                Integer.class,
                created.getTrackingNumber()))
        .isEqualTo(4);
  }

  @Test
  void webhooksStoredTogetherAreAppliedInCarrierTimeOrder() throws Exception {
    String orderId = Ids.newId();
    carrier.update(new FakeCarrierConfig(0.0, 1.0, null, null, null));
    ShipmentCreated created = book(orderId);
    List<Sent> sent = carrierSendsAll(created.getTrackingNumber());
    for (Sent s : sent) {
      postWebhook(s.body(), s.ts(), s.signature()).andExpect(status().isOk());
    }
    useCases.processTracking(100);
    List<ShipmentInTransit> inTransit = driver.published(ShipmentInTransit.class, orderId);
    assertThat(inTransit).hasSize(3);
    assertThat(inTransit.stream().map(ShipmentInTransit::getCarrierTimestamp).toList()).isSorted();
    List<MessageDriver.Published> all = driver.publishedFor(orderId);
    assertThat(all.get(all.size() - 1).record()).isInstanceOf(ShipmentDelivered.class);
    assertThat(all)
        .extracting(p -> p.envelope().getAggregateVersion())
        .containsExactly(1L, 2L, 3L, 4L, 5L);
  }

  @Test
  void badSignaturesStaleTimestampsAndJunkAreRejected() throws Exception {
    byte[] body =
        ("{\"carrierEventId\":\"ce_x\",\"trackingNumber\":\"FC1\",\"status\":\"IN_TRANSIT\","
                + "\"occurredAt\":\"2026-11-22T09:15:00.123Z\"}")
            .getBytes(StandardCharsets.UTF_8);
    long now = clock.instant().getEpochSecond();
    postWebhook(body, now, "00".repeat(32)).andExpect(status().isUnauthorized());
    postWebhook(body, now - 301, verifier.sign(now - 301, body))
        .andExpect(status().isUnauthorized());
    byte[] junk = "not json".getBytes(StandardCharsets.UTF_8);
    postWebhook(junk, now, verifier.sign(now, junk)).andExpect(status().isBadRequest());
    postWebhook(body, now, verifier.sign(now, body)).andExpect(status().isOk());
    postWebhook(body, now, verifier.sign(now, body)).andExpect(status().isOk());
    assertThat(useCases.processTracking(100)).isGreaterThanOrEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "SELECT outcome FROM tracking_event WHERE carrier_event_id = 'ce_x'", String.class))
        .isEqualTo("IGNORED_UNKNOWN_SHIPMENT");
  }

  @Test
  void issueReturnLabelBooksAReturnShipmentWithTheSagasShipmentId() {
    String orderId = Ids.newId();
    String returnId = Ids.newId();
    String shipmentId = Ids.newId();
    IssueReturnLabel cmd =
        IssueReturnLabel.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(orderId)
            .setReturnId(returnId)
            .setShipmentId(shipmentId)
            .setPickupFrom(address())
            .setToWarehouseId("wh-berlin-1")
            .build();
    driver.deliver("shipping.commands.v1", orderId, cmd, returnId, null);
    driver.deliver("shipping.commands.v1", orderId, cmd, returnId, null);
    List<ShipmentCreated> created = driver.published(ShipmentCreated.class, orderId);
    assertThat(created).hasSize(2);
    assertThat(created).allSatisfy(c -> assertThat(c.getShipmentId()).isEqualTo(shipmentId));
    assertThat(created.get(0).getDirection()).isEqualTo(ShipmentDirection.RETURN);
    assertThat(created.get(0).getReturnId()).isEqualTo(returnId);
    assertThat(created.get(0).getEnvelope().getCorrelationId()).isEqualTo(returnId);
    assertThat(carrier.bookings(shipmentId)).isEqualTo(1);
  }

  @Test
  void theFakeCarrierIsDrivenThroughTheAdminApi() throws Exception {
    String orderId = Ids.newId();
    carrier.update(new FakeCarrierConfig(null, null, null, 0, null));
    ShipmentCreated created = book(orderId);
    mvc.perform(
            put("/admin/fakes/carrier")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"duplicateRate\": 0.5}"))
        .andExpect(status().isOk())
        .andExpect(OpenApiContract.validResponse("admin.yaml"));
    assertThat(carrier.config().duplicateRate()).isEqualTo(0.5);
    assertThat(carrier.config().stepDelayMs()).isZero();

    clock.advance(Duration.ofMinutes(5));
    carrier.tick();
    assertThat(SENT)
        .as("no automatic progress with stepDelayMs=0")
        .noneMatch(
            x -> x.json().get("trackingNumber").asText().equals(created.getTrackingNumber()));
    mvc.perform(
            post("/admin/fakes/carrier/shipments/" + created.getTrackingNumber() + "/advance")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"toStatus\": \"DELIVERED\"}"))
        .andExpect(status().isAccepted())
        .andExpect(OpenApiContract.validResponse("admin.yaml"));
    mvc.perform(post("/admin/fakes/carrier/shipments/FC000/advance"))
        .andExpect(status().isNotFound());
    carrier.tick();
    Sent s =
        SENT.stream()
            .filter(
                x -> x.json().get("trackingNumber").asText().equals(created.getTrackingNumber()))
            .findFirst()
            .orElseThrow();
    assertThat(s.json().get("status").asText()).isEqualTo("DELIVERED");
    assertThat(s.json().get("occurredAt").asText()).matches(".*\\.\\d{3}Z");
    postWebhook(s.body(), s.ts(), s.signature()).andExpect(status().isOk());
    useCases.processTracking(10);
    ShipmentDelivered delivered = driver.published(ShipmentDelivered.class, orderId).get(0);
    assertThat(delivered.getDeliveredAt()).isBeforeOrEqualTo(Instant.now().plusSeconds(600));
  }
}
