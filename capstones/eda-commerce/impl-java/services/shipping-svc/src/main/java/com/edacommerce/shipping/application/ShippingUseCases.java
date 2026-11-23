package com.edacommerce.shipping.application;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.shipping.domain.Direction;
import com.edacommerce.shipping.domain.PostalAddress;
import com.edacommerce.shipping.domain.Shipment;
import com.edacommerce.shipping.domain.ShipmentEvent;
import com.edacommerce.shipping.domain.ShipmentStatus;
import com.edacommerce.shipping.domain.ShippingException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Shipping use cases. Booking runs inside the caller's unit of work (the consumer record or one
 * retry): the carrier is idempotent on shipmentId and the label key is derived from business ids,
 * so a rollback and redelivery books and stores the same thing again (ADR-0009: object first, event
 * second). Tracking webhooks are stored by the HTTP endpoint and applied here afterwards.
 */
public class ShippingUseCases {
  private static final Logger log = LoggerFactory.getLogger(ShippingUseCases.class);
  public static final String LABEL_BUCKET = "shipping-labels";

  /** Bucket lifecycle rule for labels (ADR-0009, infra/minio/init.sh). */
  public static final Duration LABEL_RETENTION = Duration.ofDays(30);

  private final ShipmentRepository shipments;
  private final TrackingEvents tracking;
  private final Carrier carrier;
  private final LabelRenderer labels;
  private final ClaimCheckStore documents;
  private final OutboxWriter outbox;
  private final TransactionTemplate tx;
  private final IdGenerator ids;
  private final Clock clock;

  public ShippingUseCases(
      ShipmentRepository shipments,
      TrackingEvents tracking,
      Carrier carrier,
      LabelRenderer labels,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      TransactionTemplate tx,
      IdGenerator ids,
      Clock clock) {
    this.shipments = shipments;
    this.tracking = tracking;
    this.carrier = carrier;
    this.labels = labels;
    this.documents = documents;
    this.outbox = outbox;
    this.tx = tx;
    this.ids = ids;
    this.clock = clock;
  }

  /** OrderPacked (choreography, ADR-0001): book the outbound parcel and print its label. */
  @Transactional
  public Shipment onOrderPacked(
      String orderId,
      String fulfilmentId,
      String warehouseId,
      PostalAddress shipTo,
      String shippingMethod,
      int parcelCount,
      Causation causation) {
    Optional<Shipment> existing = shipments.findByFulfilmentForUpdate(fulfilmentId);
    if (existing.isPresent()) {
      return again(existing.get(), causation);
    }
    Shipment s =
        Shipment.pending(
            ids.newId(),
            orderId,
            Direction.OUTBOUND,
            fulfilmentId,
            null,
            warehouseId,
            shipTo,
            parcelCount,
            shippingMethod,
            causation.correlationId(),
            causation.causationId(),
            clock.instant());
    attempt(s, causation);
    return s;
  }

  /** IssueReturnLabel from the returns saga (shipmentId minted by the saga, reused on resend). */
  @Transactional
  public Shipment issueReturnLabel(
      String orderId,
      String returnId,
      String shipmentId,
      PostalAddress pickupFrom,
      String toWarehouseId,
      Causation causation) {
    Optional<Shipment> existing = shipments.findForUpdate(shipmentId);
    if (existing.isPresent()) {
      Shipment s = existing.get();
      if (s.direction() != Direction.RETURN || !returnId.equals(s.returnId())) {
        throw new ShippingException("shipment " + shipmentId + " belongs to another flow");
      }
      return again(s, causation);
    }
    Shipment s =
        Shipment.pending(
            shipmentId,
            orderId,
            Direction.RETURN,
            null,
            returnId,
            toWarehouseId,
            pickupFrom,
            1,
            "STANDARD",
            causation.correlationId(),
            causation.causationId(),
            clock.instant());
    attempt(s, causation);
    return s;
  }

  /** A repeated request: re-answer a booking, restart a failed one, or wait for the retrier. */
  private Shipment again(Shipment s, Causation causation) {
    switch (s.status()) {
      case BOOKED -> outbox.append(ShippingMessages.event(s, createdEvent(s)), causation);
      case BOOKING_FAILED -> {
        s.restartBooking(causation.causationId(), clock.instant());
        attempt(s, causation);
      }
      case BOOKING_PENDING -> {
        // the booking retrier owns it
      }
    }
    return s;
  }

  private static ShipmentEvent createdEvent(Shipment s) {
    // The original ShipmentCreated, re-emitted with the version it was created with.
    return new ShipmentEvent.Created(s.createdVersion());
  }

  /** Retries due bookings, each in its own transaction. Returns how many were attempted. */
  public int retryDueBookings(int limit) {
    int n = 0;
    for (int i = 0; i < limit; i++) {
      Boolean done =
          tx.execute(
              status -> {
                List<String> due = shipments.lockDueBookings(clock.instant(), 1);
                if (due.isEmpty()) {
                  return Boolean.FALSE;
                }
                Shipment s = shipments.findForUpdate(due.get(0)).orElseThrow();
                attempt(s, new Causation(s.correlationId(), s.causationId()));
                return Boolean.TRUE;
              });
      if (!Boolean.TRUE.equals(done)) {
        break;
      }
      n++;
    }
    return n;
  }

  private void attempt(Shipment s, Causation causation) {
    Instant now = clock.instant();
    Carrier.Booking booking;
    try {
      booking = carrier.book(s.shipmentId(), s.direction(), s.address(), s.parcelCount());
    } catch (Carrier.UnavailableException e) {
      Optional<ShipmentEvent> gaveUp = s.bookingFailed(e.getMessage(), now);
      shipments.save(s);
      if (gaveUp.isPresent()) {
        log.error(
            "carrier booking failed {} times for shipment {}; giving up",
            s.bookingAttempts(),
            s.shipmentId());
        outbox.append(ShippingMessages.event(s, gaveUp.get()), causation);
      } else {
        log.warn(
            "carrier booking failed for shipment {}; retrying at {}",
            s.shipmentId(),
            s.nextAttemptAt());
      }
      return;
    }
    byte[] pdf = labels.render(s, booking.carrier(), booking.trackingNumber());
    String key = ClaimChecks.key("shipping", s.createdAt(), s.orderId(), s.shipmentId(), "pdf");
    // Object first: the upload happens before the transaction commits the event pointing at it.
    ClaimCheck label =
        documents.put(LABEL_BUCKET, key, pdf, "application/pdf", now.plus(LABEL_RETENTION));
    ShipmentEvent created =
        s.booked(
            booking.carrier(), booking.trackingNumber(), ShippingMessages.documentRef(label), now);
    shipments.save(s);
    outbox.append(ShippingMessages.event(s, created), causation);
  }

  /**
   * Applies stored carrier webhooks in carrier-timestamp order (webhooks.yaml rule 4: never trust
   * arrival order). Returns how many were applied.
   */
  public int processTracking(int limit) {
    Integer n =
        tx.execute(
            status -> {
              List<TrackingEvents.Stored> batch = tracking.lockUnprocessed(limit);
              for (TrackingEvents.Stored stored : batch) {
                tracking.markProcessed(stored.carrierEventId(), apply(stored));
              }
              return batch.size();
            });
    return n == null ? 0 : n;
  }

  private String apply(TrackingEvents.Stored stored) {
    if (stored.update() == null) {
      return "IGNORED_UNKNOWN_STATUS:" + stored.rawStatus();
    }
    Optional<Shipment> found =
        shipments.findByTrackingNumberForUpdate(stored.update().trackingNumber());
    if (found.isEmpty() || found.get().status() != ShipmentStatus.BOOKED) {
      log.warn("carrier update {} for an unknown tracking number", stored.carrierEventId());
      return "IGNORED_UNKNOWN_SHIPMENT";
    }
    Shipment s = found.get();
    Optional<ShipmentEvent> e = s.track(stored.update());
    if (e.isEmpty()) {
      return "STORED_ONLY";
    }
    shipments.save(s);
    // A webhook is an external trigger: the flow's correlation id, no causing message.
    outbox.append(ShippingMessages.event(s, e.get()), Causation.root(s.correlationId()));
    return "EMITTED";
  }
}
