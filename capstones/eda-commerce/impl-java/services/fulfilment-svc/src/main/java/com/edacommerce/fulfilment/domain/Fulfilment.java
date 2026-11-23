package com.edacommerce.fulfilment.domain;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/**
 * An outbound warehouse order, one per fulfilmentId (minted by order-svc). Pure: time is passed in.
 *
 * <pre>
 * REQUESTED --WMS accepted--> ACCEPTED --picked--> PICKED --packed--> PACKED --ShipmentCreated--> DISPATCHED
 *     +---- CancelFulfilment (any state before DISPATCHED) ----------------------------> CANCELLED
 *     +---- warehouse failure (before PACKED) -----------------------------------------> FAILED
 * </pre>
 *
 * <p>{@code RequestFulfilment} is safe to resend (architecture §5.8): an unknown id creates the
 * warehouse order; a known id the warehouse has not acknowledged is pushed again (it may have lost
 * it); an acknowledged id re-answers the original reply and never creates a second pick order.
 * Warehouse progress only moves forward and never revives a stopped order. Dispatch is the pivot: a
 * dispatched order cannot be cancelled (ADR-0015).
 */
public final class Fulfilment {

  /** What to do with a RequestFulfilment. */
  public enum RequestDecision {
    CREATE_AND_SUBMIT,
    RESUBMIT,
    ANSWER_ACCEPTED,
    ANSWER_CANCELLED,
    ANSWER_FAILED
  }

  /** What to do with a CancelFulfilment. */
  public enum CancelDecision {
    TOMBSTONE,
    CANCEL,
    ANSWER_CANCELLED,
    REFUSE_DISPATCHED
  }

  /** What to do with an outbound ShipmentCreated. */
  public enum DispatchDecision {
    DISPATCH,
    ANSWER_DISPATCHED,
    NOT_PACKED,
    IGNORE_STOPPED
  }

  private final String fulfilmentId;
  private final String orderId;
  private FulfilmentStatus status;
  private int attempt;
  private final List<OrderLine> lines;
  private final ShipTo shipTo;
  private final String shippingMethod;
  private String warehouseId;
  private Instant estimatedDispatchAt;
  private List<Parcel> parcels;
  private DocumentRef manifest;
  private String shipmentId;
  private FailureReason failureReason;
  private String failureDetail;
  private long acceptedVersion;
  private Instant acceptedAt;
  private Instant pickedAt;
  private Instant packedAt;
  private Instant dispatchedAt;
  private Instant cancelledAt;
  private Instant failedAt;
  private long version;
  private final Instant createdAt;

  /** Rehydrates a stored fulfilment (persistence adapter). */
  public Fulfilment(
      String fulfilmentId,
      String orderId,
      FulfilmentStatus status,
      int attempt,
      List<OrderLine> lines,
      ShipTo shipTo,
      String shippingMethod,
      String warehouseId,
      Instant estimatedDispatchAt,
      List<Parcel> parcels,
      DocumentRef manifest,
      String shipmentId,
      FailureReason failureReason,
      String failureDetail,
      long acceptedVersion,
      Instant acceptedAt,
      Instant pickedAt,
      Instant packedAt,
      Instant dispatchedAt,
      Instant cancelledAt,
      Instant failedAt,
      long version,
      Instant createdAt) {
    this.fulfilmentId = fulfilmentId;
    this.orderId = orderId;
    this.status = status;
    this.attempt = attempt;
    this.lines = List.copyOf(lines);
    this.shipTo = shipTo;
    this.shippingMethod = shippingMethod;
    this.warehouseId = warehouseId;
    this.estimatedDispatchAt = estimatedDispatchAt;
    this.parcels = parcels == null ? List.of() : List.copyOf(parcels);
    this.manifest = manifest;
    this.shipmentId = shipmentId;
    this.failureReason = failureReason;
    this.failureDetail = failureDetail;
    this.acceptedVersion = acceptedVersion;
    this.acceptedAt = acceptedAt;
    this.pickedAt = pickedAt;
    this.packedAt = packedAt;
    this.dispatchedAt = dispatchedAt;
    this.cancelledAt = cancelledAt;
    this.failedAt = failedAt;
    this.version = version;
    this.createdAt = createdAt;
  }

  /** A new warehouse order for a first RequestFulfilment. */
  public static Fulfilment requested(
      String fulfilmentId,
      String orderId,
      List<OrderLine> lines,
      ShipTo shipTo,
      String shippingMethod,
      int attempt,
      Instant now) {
    if (lines.isEmpty()) {
      throw new FulfilmentException("fulfilment " + fulfilmentId + " has no lines");
    }
    return new Fulfilment(
        fulfilmentId,
        orderId,
        FulfilmentStatus.REQUESTED,
        attempt,
        lines,
        shipTo,
        shippingMethod,
        null,
        null,
        List.of(),
        null,
        null,
        null,
        null,
        0,
        null,
        null,
        null,
        null,
        null,
        null,
        0,
        now);
  }

  /**
   * A cancel that arrived before its request (retry topics reorder): a tombstone, so a late
   * RequestFulfilment cannot start picking a cancelled order.
   */
  public static Fulfilment tombstone(String fulfilmentId, String orderId, Instant now) {
    Fulfilment f =
        new Fulfilment(
            fulfilmentId,
            orderId,
            FulfilmentStatus.CANCELLED,
            0,
            List.of(),
            null,
            "STANDARD",
            null,
            null,
            List.of(),
            null,
            null,
            null,
            null,
            0,
            null,
            null,
            null,
            null,
            now,
            null,
            1,
            now);
    return f;
  }

  public static RequestDecision decideRequest(Optional<Fulfilment> existing) {
    if (existing.isEmpty()) {
      return RequestDecision.CREATE_AND_SUBMIT;
    }
    FulfilmentStatus s = existing.get().status;
    if (s == FulfilmentStatus.REQUESTED) {
      return RequestDecision.RESUBMIT;
    }
    if (s.acknowledged()) {
      return RequestDecision.ANSWER_ACCEPTED;
    }
    return s == FulfilmentStatus.CANCELLED
        ? RequestDecision.ANSWER_CANCELLED
        : RequestDecision.ANSWER_FAILED;
  }

  public static CancelDecision decideCancel(Optional<Fulfilment> existing) {
    if (existing.isEmpty()) {
      return CancelDecision.TOMBSTONE;
    }
    return switch (existing.get().status) {
      case REQUESTED, ACCEPTED, PICKED, PACKED -> CancelDecision.CANCEL;
      case DISPATCHED -> CancelDecision.REFUSE_DISPATCHED;
      case CANCELLED, FAILED -> CancelDecision.ANSWER_CANCELLED;
    };
  }

  public static DispatchDecision decideDispatch(Optional<Fulfilment> existing) {
    if (existing.isEmpty()) {
      return DispatchDecision.NOT_PACKED;
    }
    return switch (existing.get().status) {
      case REQUESTED, ACCEPTED, PICKED -> DispatchDecision.NOT_PACKED;
      case PACKED -> DispatchDecision.DISPATCH;
      case DISPATCHED -> DispatchDecision.ANSWER_DISPATCHED;
      case CANCELLED, FAILED -> DispatchDecision.IGNORE_STOPPED;
    };
  }

  /** A resend that is pushed to the warehouse again records the attempt it came with. */
  public void resubmitted(int attempt) {
    this.attempt = Math.max(this.attempt, attempt);
  }

  public Optional<FulfilmentEvent> accept(String warehouseId, Instant eta, Instant now) {
    if (status != FulfilmentStatus.REQUESTED) {
      return Optional.empty();
    }
    status = FulfilmentStatus.ACCEPTED;
    this.warehouseId = warehouseId;
    this.estimatedDispatchAt = eta;
    this.acceptedAt = now;
    this.acceptedVersion = ++version;
    return Optional.of(new FulfilmentEvent.Accepted(acceptedVersion));
  }

  public Optional<FulfilmentEvent> pick(Instant now) {
    if (status != FulfilmentStatus.ACCEPTED) {
      return Optional.empty();
    }
    status = FulfilmentStatus.PICKED;
    pickedAt = now;
    return Optional.of(new FulfilmentEvent.Picked(++version));
  }

  /** True if a packed report would apply (checked before the manifest is uploaded). */
  public boolean canPack() {
    return status == FulfilmentStatus.PICKED;
  }

  public Optional<FulfilmentEvent> pack(List<Parcel> parcels, DocumentRef manifest, Instant now) {
    if (!canPack()) {
      return Optional.empty();
    }
    if (parcels.isEmpty()) {
      throw new FulfilmentException("packed without parcels: " + fulfilmentId);
    }
    status = FulfilmentStatus.PACKED;
    this.parcels = List.copyOf(parcels);
    this.manifest = manifest;
    packedAt = now;
    return Optional.of(new FulfilmentEvent.Packed(++version));
  }

  public Optional<FulfilmentEvent> fail(FailureReason reason, String detail, Instant now) {
    if (status != FulfilmentStatus.REQUESTED
        && status != FulfilmentStatus.ACCEPTED
        && status != FulfilmentStatus.PICKED) {
      return Optional.empty();
    }
    status = FulfilmentStatus.FAILED;
    failureReason = reason;
    failureDetail = detail;
    failedAt = now;
    return Optional.of(new FulfilmentEvent.Failed(++version));
  }

  public FulfilmentEvent cancel(Instant now) {
    if (decideCancel(Optional.of(this)) != CancelDecision.CANCEL) {
      throw new FulfilmentException("fulfilment " + fulfilmentId + " cannot be cancelled now");
    }
    status = FulfilmentStatus.CANCELLED;
    cancelledAt = now;
    return new FulfilmentEvent.Cancelled(++version);
  }

  public FulfilmentEvent dispatch(String shipmentId, Instant now) {
    if (status != FulfilmentStatus.PACKED) {
      throw new FulfilmentException("fulfilment " + fulfilmentId + " is not packed");
    }
    status = FulfilmentStatus.DISPATCHED;
    this.shipmentId = shipmentId;
    dispatchedAt = now;
    return new FulfilmentEvent.Dispatched(++version);
  }

  /** The reply a resent request gets: the original one, with the version it was emitted at. */
  public FulfilmentEvent currentReply() {
    if (status.acknowledged()) {
      return new FulfilmentEvent.Accepted(acceptedVersion);
    }
    if (status == FulfilmentStatus.CANCELLED) {
      return new FulfilmentEvent.Cancelled(version);
    }
    if (status == FulfilmentStatus.FAILED) {
      return new FulfilmentEvent.Failed(version);
    }
    throw new FulfilmentException("no reply yet for " + fulfilmentId);
  }

  public String fulfilmentId() {
    return fulfilmentId;
  }

  public String orderId() {
    return orderId;
  }

  public FulfilmentStatus status() {
    return status;
  }

  public int attempt() {
    return attempt;
  }

  public List<OrderLine> lines() {
    return lines;
  }

  public ShipTo shipTo() {
    return shipTo;
  }

  public String shippingMethod() {
    return shippingMethod;
  }

  public String warehouseId() {
    return warehouseId;
  }

  public Instant estimatedDispatchAt() {
    return estimatedDispatchAt;
  }

  public List<Parcel> parcels() {
    return parcels;
  }

  public DocumentRef manifest() {
    return manifest;
  }

  public String shipmentId() {
    return shipmentId;
  }

  public FailureReason failureReason() {
    return failureReason;
  }

  public String failureDetail() {
    return failureDetail;
  }

  public long acceptedVersion() {
    return acceptedVersion;
  }

  public Instant acceptedAt() {
    return acceptedAt;
  }

  public Instant pickedAt() {
    return pickedAt;
  }

  public Instant packedAt() {
    return packedAt;
  }

  public Instant dispatchedAt() {
    return dispatchedAt;
  }

  public Instant cancelledAt() {
    return cancelledAt;
  }

  public Instant failedAt() {
    return failedAt;
  }

  public long version() {
    return version;
  }

  public Instant createdAt() {
    return createdAt;
  }
}
