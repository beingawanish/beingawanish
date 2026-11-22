package com.edacommerce.fulfilment.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.fulfilment.CancelFulfilment;
import com.edacommerce.fulfilment.ExpectReturn;
import com.edacommerce.fulfilment.RequestFulfilment;
import com.edacommerce.fulfilment.application.FulfilmentMessages;
import com.edacommerce.fulfilment.domain.DocumentRef;
import com.edacommerce.fulfilment.domain.FailureReason;
import com.edacommerce.fulfilment.domain.Fulfilment;
import com.edacommerce.fulfilment.domain.FulfilmentEvent;
import com.edacommerce.fulfilment.domain.InspectionOutcome;
import com.edacommerce.fulfilment.domain.OrderLine;
import com.edacommerce.fulfilment.domain.Parcel;
import com.edacommerce.fulfilment.domain.ReturnIntake;
import com.edacommerce.fulfilment.domain.ReturnLine;
import com.edacommerce.fulfilment.domain.ShipTo;
import com.edacommerce.shipping.ShipmentCreated;
import com.edacommerce.shipping.ShipmentDelivered;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** Layer 2: golden messages this service consumes decode; everything it produces validates. */
class FulfilmentContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @Test
  void consumedMessagesDecodeFromTheirGoldenBytes() {
    RequestFulfilment request = GoldenFixtures.assertSpecificRoundTrip(RequestFulfilment.class);
    assertThat(request.getLines()).isNotEmpty();
    GoldenFixtures.assertSpecificRoundTrip(CancelFulfilment.class);
    GoldenFixtures.assertSpecificRoundTrip(ExpectReturn.class);
    GoldenFixtures.assertSpecificRoundTrip(ShipmentCreated.class);
    GoldenFixtures.assertSpecificRoundTrip(ShipmentDelivered.class);
    assertThat(FulfilmentMessages.shipTo(request.getShipTo()).countryCode())
        .isEqualTo(request.getShipTo().getCountryCode());
  }

  @Test
  void everyProducedMessageValidatesAgainstTheBundledSchema() {
    ShipTo to = new ShipTo("Ada", "Main 1", null, "Berlin", null, "10115", "DE", null);
    Fulfilment f =
        Fulfilment.requested(
            "f1", "o1", List.of(new OrderLine("l1", "SKU-1", "Mug", 1)), to, "EXPRESS", 1, T);
    f.accept("wh", T, T);
    f.pick(T);
    f.pack(
        List.of(new Parcel("p1", 450, 400, 300, 150)),
        new DocumentRef("packing-manifests", "k", "application/json", 10, "ab", T),
        T);
    f.dispatch("s1", T);
    Fulfilment failed =
        Fulfilment.requested(
            "f2", "o1", List.of(new OrderLine("l1", "SKU-1", "Mug", 1)), to, "STANDARD", 1, T);
    failed.fail(FailureReason.ADDRESS_UNSERVICEABLE, "no", T);
    Fulfilment cancelled = Fulfilment.tombstone("f3", "o1", T);
    List<OutgoingMessage> produced =
        List.of(
            FulfilmentMessages.event(f, new FulfilmentEvent.Accepted(1)),
            FulfilmentMessages.event(f, new FulfilmentEvent.Picked(2)),
            FulfilmentMessages.event(f, new FulfilmentEvent.Packed(3)),
            FulfilmentMessages.event(f, new FulfilmentEvent.Dispatched(4)),
            FulfilmentMessages.event(failed, failed.currentReply()),
            FulfilmentMessages.event(cancelled, cancelled.currentReply()));
    for (OutgoingMessage m : produced) {
      assertThat(m.topic()).isEqualTo("fulfilment.events.v1");
      assertThat(m.key()).isEqualTo("o1");
      assertThat(m.aggregateType()).isEqualTo("Fulfilment");
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
    ReturnIntake r =
        ReturnIntake.expect("r1", "o1", "RMA-1", List.of(new ReturnLine("l1", "SKU-1", 2)), T);
    r.receive(T);
    GoldenFixtures.assertValidAgainstBundled(FulfilmentMessages.returnReceived(r, 1).record());
    r.inspect(Map.of("l1", List.of(InspectionOutcome.DAMAGED)), T);
    OutgoingMessage inspected = FulfilmentMessages.returnInspected(r, 2);
    assertThat(inspected.key()).isEqualTo("o1");
    GoldenFixtures.assertValidAgainstBundled(inspected.record());
  }
}
