package com.edacommerce.shipping.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.fulfilment.OrderPacked;
import com.edacommerce.shipping.IssueReturnLabel;
import com.edacommerce.shipping.application.ShippingMessages;
import com.edacommerce.shipping.domain.CarrierStatus;
import com.edacommerce.shipping.domain.Direction;
import com.edacommerce.shipping.domain.DocumentRef;
import com.edacommerce.shipping.domain.PostalAddress;
import com.edacommerce.shipping.domain.Shipment;
import com.edacommerce.shipping.domain.TrackingUpdate;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Layer 2: golden messages this service consumes decode; everything it produces validates. */
class ShippingContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @Test
  void consumedMessagesDecodeFromTheirGoldenBytes() {
    OrderPacked packed = GoldenFixtures.assertSpecificRoundTrip(OrderPacked.class);
    assertThat(ShippingMessages.address(packed.getShipTo()).city())
        .isEqualTo(packed.getShipTo().getCity());
    GoldenFixtures.assertSpecificRoundTrip(IssueReturnLabel.class);
  }

  @Test
  void everyProducedMessageValidatesAgainstTheBundledSchema() {
    PostalAddress a = new PostalAddress("Ada", "Main 1", null, "Berlin", null, "10115", "DE", null);
    for (Direction d : Direction.values()) {
      Shipment s =
          Shipment.pending(
              "s1",
              "o1",
              d,
              d == Direction.OUTBOUND ? "f1" : null,
              d == Direction.RETURN ? "r1" : null,
              "wh",
              a,
              1,
              "STANDARD",
              "o1",
              null,
              T);
      List<OutgoingMessage> out = new ArrayList<>();
      out.add(
          ShippingMessages.event(
              s,
              s.booked(
                  "fake-carrier",
                  "FC1",
                  new DocumentRef("shipping-labels", "k", "application/pdf", 1, "ab", T),
                  T)));
      for (CarrierStatus st :
          List.of(CarrierStatus.IN_TRANSIT, CarrierStatus.DELIVERED, CarrierStatus.EXCEPTION)) {
        s.track(new TrackingUpdate("c-" + st, "FC1", st, "LOST", "hub", T))
            .ifPresent(e -> out.add(ShippingMessages.event(s, e)));
      }
      assertThat(out).hasSize(4);
      for (OutgoingMessage m : out) {
        assertThat(m.topic()).isEqualTo("shipping.events.v1");
        assertThat(m.key()).isEqualTo("o1");
        GoldenFixtures.assertValidAgainstBundled(m.record());
      }
    }
  }
}
