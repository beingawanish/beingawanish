package com.edacommerce.shipping.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.shipping.adapters.out.carrier.fake.FakeCarrier;
import com.edacommerce.shipping.domain.CarrierStatus;
import com.edacommerce.shipping.domain.Direction;
import com.edacommerce.shipping.domain.DocumentRef;
import com.edacommerce.shipping.domain.PostalAddress;
import com.edacommerce.shipping.domain.Shipment;
import com.edacommerce.shipping.domain.ShipmentEvent;
import com.edacommerce.shipping.domain.ShipmentStatus;
import com.edacommerce.shipping.domain.ShippingException;
import com.edacommerce.shipping.domain.TrackingUpdate;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;
import java.util.Random;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import org.junit.jupiter.api.Test;

/** Layer 1: booking retries and tracking normalisation (architecture §5.10). */
class ShipmentTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");
  static final PostalAddress A =
      new PostalAddress("Ada", "Main 1", null, "Berlin", null, "10115", "DE", null);
  static final DocumentRef LABEL =
      new DocumentRef("shipping-labels", "k", "application/pdf", 10, "ab", T);

  static Shipment booked() {
    Shipment s =
        Shipment.pending(
            "s1", "o1", Direction.OUTBOUND, "f1", null, "wh", A, 1, "STANDARD", "o1", null, T);
    s.booked("fake-carrier", "FC1", LABEL, T);
    return s;
  }

  static TrackingUpdate u(String id, CarrierStatus status, int minute) {
    return new TrackingUpdate(id, "FC1", status, null, null, T.plusSeconds(60L * minute));
  }

  @Test
  void bookingBacksOffThenGivesUpAfterFiveAttemptsAndCanBeRestarted() {
    Shipment s =
        Shipment.pending(
            "s1", "o1", Direction.RETURN, null, "r1", "wh", A, 1, "STANDARD", "r1", null, T);
    assertThat(s.bookingFailed("503", T)).isEmpty();
    assertThat(s.nextAttemptAt()).isEqualTo(T.plusSeconds(10));
    assertThat(s.bookingFailed("503", T)).isEmpty();
    assertThat(s.nextAttemptAt()).isEqualTo(T.plus(Duration.ofMinutes(1)));
    s.bookingFailed("503", T);
    s.bookingFailed("503", T);
    assertThat(s.nextAttemptAt()).isEqualTo(T.plus(Duration.ofHours(1)));
    Optional<ShipmentEvent> gaveUp = s.bookingFailed("503", T);
    assertThat(gaveUp).containsInstanceOf(ShipmentEvent.Problem.class);
    assertThat(((ShipmentEvent.Problem) gaveUp.orElseThrow()).code()).isEqualTo("BOOKING_FAILED");
    assertThat(s.status()).isEqualTo(ShipmentStatus.BOOKING_FAILED);
    assertThat(s.restartBooking("cause", T)).isTrue();
    assertThat(s.status()).isEqualTo(ShipmentStatus.BOOKING_PENDING);
    assertThat(s.bookingAttempts()).isZero();
    assertThat(s.booked("c", "FC9", LABEL, T)).isEqualTo(new ShipmentEvent.Created(2));
    assertThat(s.createdVersion()).isEqualTo(2);
  }

  @Test
  void aShipmentNeedsItsFlowId() {
    assertThatThrownBy(
            () ->
                Shipment.pending(
                    "s", "o", Direction.OUTBOUND, null, null, "wh", A, 1, "STANDARD", "o", null, T))
        .isInstanceOf(ShippingException.class);
    assertThatThrownBy(
            () ->
                Shipment.pending(
                    "s", "o", Direction.RETURN, null, null, "wh", A, 1, "STANDARD", "o", null, T))
        .isInstanceOf(ShippingException.class);
  }

  @Test
  void deliveredBeforeInTransitEmitsDeliveredOnceAndNothingBackwards() {
    Shipment s = booked();
    assertThat(s.track(u("c3", CarrierStatus.DELIVERED, 300)))
        .containsInstanceOf(ShipmentEvent.Delivered.class);
    assertThat(s.track(u("c2", CarrierStatus.IN_TRANSIT, 100))).isEmpty();
    assertThat(s.track(u("c3", CarrierStatus.DELIVERED, 300))).isEmpty();
    assertThat(s.deliveredAt()).isEqualTo(T.plusSeconds(60L * 300));
  }

  @Test
  void forwardMovesAreReportedEachOnceAndLabelCreatedIsSilent() {
    Shipment s = booked();
    assertThat(s.track(u("c0", CarrierStatus.LABEL_CREATED, 1))).isEmpty();
    assertThat(s.track(u("c1", CarrierStatus.PICKED_UP, 2)))
        .containsInstanceOf(ShipmentEvent.InTransit.class);
    assertThat(s.track(u("c2", CarrierStatus.IN_TRANSIT, 3)))
        .containsInstanceOf(ShipmentEvent.InTransit.class);
    assertThat(s.track(u("c2b", CarrierStatus.IN_TRANSIT, 4))).isEmpty();
    assertThat(s.track(u("c3", CarrierStatus.OUT_FOR_DELIVERY, 5))).isPresent();
    assertThat(s.version()).isEqualTo(4);
  }

  @Test
  void exceptionsAreAlwaysReportedAndUnknownCodesBecomeUnknown() {
    Shipment s = booked();
    s.track(u("c4", CarrierStatus.DELIVERED, 9));
    Optional<ShipmentEvent> e =
        s.track(new TrackingUpdate("c5", "FC1", CarrierStatus.EXCEPTION, "LOST", null, T));
    assertThat(((ShipmentEvent.Problem) e.orElseThrow()).code()).isEqualTo("LOST");
    Optional<ShipmentEvent> unknown =
        s.track(new TrackingUpdate("c6", "FC1", CarrierStatus.EXCEPTION, "ALIENS", null, T));
    assertThat(((ShipmentEvent.Problem) unknown.orElseThrow()).code()).isEqualTo("UNKNOWN");
    assertThat(CarrierStatus.parse("TELEPORTED")).isEmpty();
  }

  @Property(tries = 300)
  void anyArrivalOrderWithDuplicatesYieldsMonotonicUniqueEvents(@ForAll long seed) {
    List<TrackingUpdate> updates = new ArrayList<>();
    CarrierStatus[] plan = {
      CarrierStatus.PICKED_UP,
      CarrierStatus.IN_TRANSIT,
      CarrierStatus.OUT_FOR_DELIVERY,
      CarrierStatus.DELIVERED
    };
    for (int i = 0; i < plan.length; i++) {
      TrackingUpdate x = u("c" + i, plan[i], i);
      updates.add(x);
      updates.add(x); // the carrier duplicates
    }
    Collections.shuffle(updates, new Random(seed));
    Shipment s = booked();
    List<ShipmentEvent> emitted = new ArrayList<>();
    java.util.Set<String> seen = new java.util.HashSet<>();
    for (TrackingUpdate x : updates) {
      if (seen.add(x.carrierEventId())) { // the inbox drops exact duplicates
        s.track(x).ifPresent(emitted::add);
      }
    }
    assertThat(emitted.stream().filter(e -> e instanceof ShipmentEvent.Delivered)).hasSize(1);
    List<Instant> times =
        emitted.stream()
            .map(
                e ->
                    e instanceof ShipmentEvent.InTransit t
                        ? t.carrierTimestamp()
                        : ((ShipmentEvent.Delivered) e).deliveredAt())
            .toList();
    assertThat(times).isSorted();
    assertThat(emitted).last().isInstanceOf(ShipmentEvent.Delivered.class);
  }

  @Test
  void trackingNumbersAreDeterministicPerShipment() {
    assertThat(FakeCarrier.trackingNumberFor("s1")).isEqualTo(FakeCarrier.trackingNumberFor("s1"));
    assertThat(FakeCarrier.trackingNumberFor("s1")).matches("FC\\d{12}");
    assertThat(FakeCarrier.trackingNumberFor("s1"))
        .isNotEqualTo(FakeCarrier.trackingNumberFor("s2"));
  }
}
