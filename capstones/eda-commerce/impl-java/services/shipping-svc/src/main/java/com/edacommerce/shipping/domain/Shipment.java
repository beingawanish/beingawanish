package com.edacommerce.shipping.domain;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.Set;

/**
 * A carrier shipment (architecture §5.10). Pure: time is passed in.
 *
 * <pre>
 * BOOKING_PENDING --carrier booked--> BOOKED
 *       | carrier unavailable: retry after 10 s, 1 min, 10 min, 1 h
 *       +--- 5 failed attempts ---> BOOKING_FAILED (ShipmentException BOOKING_FAILED)
 * </pre>
 *
 * A resent IssueReturnLabel (or a repeated OrderPacked) for a BOOKING_FAILED shipment starts the
 * attempts again: forward recovery driven by the upstream timeouts.
 *
 * <p>Tracking: carriers send duplicates and send "delivered" before "in transit". Only forward
 * moves are reported, each status at most once (rank LABEL_CREATED=0 .. DELIVERED=4); EXCEPTION is
 * reported every time a new carrier event carries it. Downstream never sees a shipment move
 * backwards.
 */
public final class Shipment {
  public static final List<Duration> BOOKING_BACKOFF =
      List.of(
          Duration.ofSeconds(10),
          Duration.ofMinutes(1),
          Duration.ofMinutes(10),
          Duration.ofHours(1));
  public static final int MAX_BOOKING_ATTEMPTS = 5;
  public static final Set<String> EXCEPTION_CODES =
      Set.of("ADDRESS_ISSUE", "DAMAGED", "LOST", "DELAYED");

  private final String shipmentId;
  private final String orderId;
  private final Direction direction;
  private final String fulfilmentId;
  private final String returnId;
  private final String warehouseId;
  private final PostalAddress address;
  private final int parcelCount;
  private final String shippingMethod;
  private ShipmentStatus status;
  private String carrier;
  private String trackingNumber;
  private DocumentRef label;
  private int bookingAttempts;
  private Instant nextAttemptAt;
  private Instant bookedAt;
  private int trackingRank;
  private Instant deliveredAt;
  private long createdVersion;
  private final String correlationId;
  private String causationId;
  private long version;
  private final Instant createdAt;

  public Shipment(
      String shipmentId,
      String orderId,
      Direction direction,
      String fulfilmentId,
      String returnId,
      String warehouseId,
      PostalAddress address,
      int parcelCount,
      String shippingMethod,
      ShipmentStatus status,
      String carrier,
      String trackingNumber,
      DocumentRef label,
      int bookingAttempts,
      Instant nextAttemptAt,
      Instant bookedAt,
      int trackingRank,
      Instant deliveredAt,
      long createdVersion,
      String correlationId,
      String causationId,
      long version,
      Instant createdAt) {
    this.shipmentId = shipmentId;
    this.orderId = orderId;
    this.direction = direction;
    this.fulfilmentId = fulfilmentId;
    this.returnId = returnId;
    this.warehouseId = warehouseId;
    this.address = address;
    this.parcelCount = parcelCount;
    this.shippingMethod = shippingMethod;
    this.status = status;
    this.carrier = carrier;
    this.trackingNumber = trackingNumber;
    this.label = label;
    this.bookingAttempts = bookingAttempts;
    this.nextAttemptAt = nextAttemptAt;
    this.bookedAt = bookedAt;
    this.trackingRank = trackingRank;
    this.deliveredAt = deliveredAt;
    this.createdVersion = createdVersion;
    this.correlationId = correlationId;
    this.causationId = causationId;
    this.version = version;
    this.createdAt = createdAt;
  }

  /** A new shipment waiting for its first booking attempt. */
  public static Shipment pending(
      String shipmentId,
      String orderId,
      Direction direction,
      String fulfilmentId,
      String returnId,
      String warehouseId,
      PostalAddress address,
      int parcelCount,
      String shippingMethod,
      String correlationId,
      String causationId,
      Instant now) {
    if (direction == Direction.OUTBOUND && fulfilmentId == null) {
      throw new ShippingException("an outbound shipment needs a fulfilmentId");
    }
    if (direction == Direction.RETURN && returnId == null) {
      throw new ShippingException("a return shipment needs a returnId");
    }
    return new Shipment(
        shipmentId,
        orderId,
        direction,
        fulfilmentId,
        returnId,
        warehouseId,
        address,
        Math.max(1, parcelCount),
        shippingMethod,
        ShipmentStatus.BOOKING_PENDING,
        null,
        null,
        null,
        0,
        now,
        null,
        0,
        null,
        0,
        correlationId,
        causationId,
        0,
        now);
  }

  /** The carrier booked it and the label is stored: ShipmentCreated. */
  public ShipmentEvent booked(
      String carrier, String trackingNumber, DocumentRef label, Instant now) {
    if (status == ShipmentStatus.BOOKED) {
      throw new ShippingException("shipment " + shipmentId + " is already booked");
    }
    status = ShipmentStatus.BOOKED;
    this.carrier = carrier;
    this.trackingNumber = trackingNumber;
    this.label = label;
    bookingAttempts++;
    nextAttemptAt = null;
    bookedAt = now;
    createdVersion = ++version;
    return new ShipmentEvent.Created(createdVersion);
  }

  /**
   * A booking attempt failed. Either the next attempt is scheduled (empty) or the shipment gives up
   * with ShipmentException(BOOKING_FAILED).
   */
  public Optional<ShipmentEvent> bookingFailed(String detail, Instant now) {
    bookingAttempts++;
    if (bookingAttempts >= MAX_BOOKING_ATTEMPTS) {
      status = ShipmentStatus.BOOKING_FAILED;
      nextAttemptAt = null;
      return Optional.of(
          new ShipmentEvent.Problem(
              ++version,
              "BOOKING_FAILED",
              "carrier booking failed " + bookingAttempts + " times: " + detail,
              null,
              now));
    }
    nextAttemptAt =
        now.plus(BOOKING_BACKOFF.get(Math.min(bookingAttempts - 1, BOOKING_BACKOFF.size() - 1)));
    return Optional.empty();
  }

  /** A repeated request for a shipment that gave up: try again from the start. */
  public boolean restartBooking(String causationId, Instant now) {
    if (status != ShipmentStatus.BOOKING_FAILED) {
      return false;
    }
    status = ShipmentStatus.BOOKING_PENDING;
    bookingAttempts = 0;
    nextAttemptAt = now;
    this.causationId = causationId;
    return true;
  }

  /**
   * Applies one carrier update: at most one event, never backwards (architecture §5.10). Empty when
   * the update is only stored for history.
   */
  public Optional<ShipmentEvent> track(TrackingUpdate u) {
    if (status != ShipmentStatus.BOOKED) {
      throw new ShippingException("tracking update for unbooked shipment " + shipmentId);
    }
    if (u.status() == CarrierStatus.EXCEPTION) {
      String code =
          u.exceptionCode() != null && EXCEPTION_CODES.contains(u.exceptionCode())
              ? u.exceptionCode()
              : "UNKNOWN";
      return Optional.of(
          new ShipmentEvent.Problem(
              ++version, code, "carrier exception", u.carrierEventId(), u.occurredAt()));
    }
    int rank = u.status().rank();
    if (rank <= trackingRank) {
      return Optional.empty();
    }
    trackingRank = rank;
    if (u.status() == CarrierStatus.DELIVERED) {
      deliveredAt = u.occurredAt();
      return Optional.of(
          new ShipmentEvent.Delivered(++version, u.carrierEventId(), u.occurredAt()));
    }
    return Optional.of(
        new ShipmentEvent.InTransit(++version, u.carrierEventId(), u.location(), u.occurredAt()));
  }

  public String shipmentId() {
    return shipmentId;
  }

  public String orderId() {
    return orderId;
  }

  public Direction direction() {
    return direction;
  }

  public String fulfilmentId() {
    return fulfilmentId;
  }

  public String returnId() {
    return returnId;
  }

  public String warehouseId() {
    return warehouseId;
  }

  public PostalAddress address() {
    return address;
  }

  public int parcelCount() {
    return parcelCount;
  }

  public String shippingMethod() {
    return shippingMethod;
  }

  public ShipmentStatus status() {
    return status;
  }

  public String carrier() {
    return carrier;
  }

  public String trackingNumber() {
    return trackingNumber;
  }

  public DocumentRef label() {
    return label;
  }

  public int bookingAttempts() {
    return bookingAttempts;
  }

  public Instant nextAttemptAt() {
    return nextAttemptAt;
  }

  public Instant bookedAt() {
    return bookedAt;
  }

  public int trackingRank() {
    return trackingRank;
  }

  public Instant deliveredAt() {
    return deliveredAt;
  }

  /** The version ShipmentCreated was emitted with (a re-emitted one keeps it). */
  public long createdVersion() {
    return createdVersion;
  }

  public String correlationId() {
    return correlationId;
  }

  public String causationId() {
    return causationId;
  }

  public long version() {
    return version;
  }

  public Instant createdAt() {
    return createdAt;
  }
}
