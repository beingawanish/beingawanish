package com.edacommerce.fulfilment.application;

import com.edacommerce.common.ClaimCheck;
import com.edacommerce.edacommon.claimcheck.ClaimCheckStore;
import com.edacommerce.edacommon.claimcheck.ClaimChecks;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.fulfilment.domain.FailureReason;
import com.edacommerce.fulfilment.domain.Fulfilment;
import com.edacommerce.fulfilment.domain.FulfilmentEvent;
import com.edacommerce.fulfilment.domain.InspectionOutcome;
import com.edacommerce.fulfilment.domain.OrderLine;
import com.edacommerce.fulfilment.domain.Parcel;
import com.edacommerce.fulfilment.domain.ReturnIntake;
import com.edacommerce.fulfilment.domain.ReturnLine;
import com.edacommerce.fulfilment.domain.ShipTo;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * fulfilment-svc's use cases. Commands and choreographed events run in the consumer's transaction
 * (inbox + change + outbox commit together); warehouse feedback runs in its own transaction. Each
 * locks the fulfilment row first, lets the domain decide, saves, and appends the facts.
 */
public class FulfilmentUseCases implements WarehouseFeedback {
  private static final Logger log = LoggerFactory.getLogger(FulfilmentUseCases.class);
  public static final String MANIFEST_BUCKET = "packing-manifests";

  /** Bucket lifecycle rule for manifests (ADR-0009, infra/minio/init.sh). */
  public static final Duration MANIFEST_RETENTION = Duration.ofDays(90);

  private final FulfilmentRepository fulfilments;
  private final ReturnIntakeRepository intakes;
  private final Warehouse warehouse;
  private final ClaimCheckStore documents;
  private final OutboxWriter outbox;
  private final TransactionTemplate tx;
  private final Clock clock;

  public FulfilmentUseCases(
      FulfilmentRepository fulfilments,
      ReturnIntakeRepository intakes,
      Warehouse warehouse,
      ClaimCheckStore documents,
      OutboxWriter outbox,
      TransactionTemplate tx,
      Clock clock) {
    this.fulfilments = fulfilments;
    this.intakes = intakes;
    this.warehouse = warehouse;
    this.documents = documents;
    this.outbox = outbox;
    this.tx = tx;
    this.clock = clock;
  }

  /** RequestFulfilment: create and submit, push again, or re-answer (architecture §5.8). */
  @Transactional
  public Fulfilment.RequestDecision request(
      String orderId,
      String fulfilmentId,
      List<OrderLine> lines,
      ShipTo shipTo,
      String shippingMethod,
      int attempt,
      Causation causation) {
    Instant now = clock.instant();
    Optional<Fulfilment> existing = fulfilments.findForUpdate(fulfilmentId);
    Fulfilment.RequestDecision decision = Fulfilment.decideRequest(existing);
    switch (decision) {
      case CREATE_AND_SUBMIT -> {
        Fulfilment f =
            Fulfilment.requested(
                fulfilmentId, orderId, lines, shipTo, shippingMethod, attempt, now);
        fulfilments.save(f);
        // A submit before commit is safe: the warehouse is idempotent on fulfilmentId, so a
        // rollback and redelivery never creates a second pick order.
        warehouse.submit(new Warehouse.PickOrder(fulfilmentId, orderId, f.lines()));
      }
      case RESUBMIT -> {
        Fulfilment f = existing.orElseThrow();
        f.resubmitted(attempt);
        fulfilments.save(f);
        warehouse.submit(new Warehouse.PickOrder(fulfilmentId, f.orderId(), f.lines()));
      }
      case ANSWER_ACCEPTED, ANSWER_CANCELLED, ANSWER_FAILED -> {
        Fulfilment f = existing.orElseThrow();
        outbox.append(FulfilmentMessages.event(f, f.currentReply()), causation);
      }
    }
    return decision;
  }

  /** CancelFulfilment (the order saga's compensation). */
  @Transactional
  public Fulfilment.CancelDecision cancel(
      String orderId, String fulfilmentId, Causation causation) {
    Instant now = clock.instant();
    Optional<Fulfilment> existing = fulfilments.findForUpdate(fulfilmentId);
    Fulfilment.CancelDecision decision = Fulfilment.decideCancel(existing);
    switch (decision) {
      case TOMBSTONE -> {
        Fulfilment f = Fulfilment.tombstone(fulfilmentId, orderId, now);
        fulfilments.save(f);
        outbox.append(FulfilmentMessages.event(f, f.currentReply()), causation);
      }
      case CANCEL -> {
        Fulfilment f = existing.orElseThrow();
        FulfilmentEvent e = f.cancel(now);
        fulfilments.save(f);
        warehouse.cancel(fulfilmentId);
        outbox.append(FulfilmentMessages.event(f, e), causation);
      }
      case ANSWER_CANCELLED -> {
        Fulfilment f = existing.orElseThrow();
        outbox.append(FulfilmentMessages.event(f, f.currentReply()), causation);
      }
      case REFUSE_DISPATCHED ->
          throw new com.edacommerce.fulfilment.domain.FulfilmentException(
              "fulfilment " + fulfilmentId + " is dispatched; past the pivot only a human decides");
    }
    return decision;
  }

  /** ShipmentCreated(OUTBOUND) from shipping-svc: the parcel leaves (choreography, ADR-0001). */
  @Transactional
  public Fulfilment.DispatchDecision dispatch(
      String fulfilmentId, String shipmentId, Causation causation) {
    Instant now = clock.instant();
    Optional<Fulfilment> existing = fulfilments.findForUpdate(fulfilmentId);
    Fulfilment.DispatchDecision decision = Fulfilment.decideDispatch(existing);
    switch (decision) {
      case DISPATCH -> {
        Fulfilment f = existing.orElseThrow();
        FulfilmentEvent e = f.dispatch(shipmentId, now);
        fulfilments.save(f);
        outbox.append(FulfilmentMessages.event(f, e), causation);
      }
      case ANSWER_DISPATCHED -> {
        // shipping re-emitted ShipmentCreated; the dispatch already happened, nothing changes.
      }
      case NOT_PACKED ->
          // Shipping books only after OrderPacked, so this is a reordered retry: try again later.
          throw new RetryLaterException("fulfilment " + fulfilmentId + " not packed yet");
      case IGNORE_STOPPED ->
          log.warn("shipment booked for a stopped fulfilment {}; label unused", fulfilmentId);
    }
    return decision;
  }

  /** ExpectReturn from the returns saga. A resend changes nothing. */
  @Transactional
  public boolean expectReturn(
      String orderId,
      String returnId,
      String rmaNumber,
      List<ReturnLine> lines,
      Instant expectedBy) {
    if (intakes.findIntakeForUpdate(returnId).isPresent()) {
      return false;
    }
    intakes.saveIntake(ReturnIntake.expect(returnId, orderId, rmaNumber, lines, expectedBy));
    return true;
  }

  /** ShipmentDelivered(RETURN): the parcel is at the warehouse; emit ReturnReceived, inspect. */
  @Transactional
  public boolean returnDelivered(String returnId, Causation causation) {
    ReturnIntake intake =
        intakes
            .findIntakeForUpdate(returnId)
            .orElseThrow(() -> new RetryLaterException("return " + returnId + " not expected yet"));
    Optional<Long> version = intake.receive(clock.instant());
    if (version.isEmpty()) {
      return false;
    }
    intakes.saveIntake(intake);
    outbox.append(FulfilmentMessages.returnReceived(intake, version.get()), causation);
    warehouse.inspect(returnId, intake.lines());
    return true;
  }

  // ------------------------------------------------------------------ warehouse feedback

  @Override
  @Transactional
  public void accepted(String fulfilmentId, String warehouseId, Instant estimatedDispatchAt) {
    onFulfilment(fulfilmentId, f -> f.accept(warehouseId, estimatedDispatchAt, clock.instant()));
  }

  @Override
  @Transactional
  public void picked(String fulfilmentId) {
    onFulfilment(fulfilmentId, f -> f.pick(clock.instant()));
  }

  @Override
  @Transactional
  public void failed(String fulfilmentId, FailureReason reason, String detail) {
    onFulfilment(fulfilmentId, f -> f.fail(reason, detail, clock.instant()));
  }

  /**
   * Object first, event second (ADR-0009): the manifest is uploaded under a key derived from the
   * business ids before the transaction that writes OrderPacked, so a retry overwrites the same
   * object and no event ever points at a missing one. If the upload fails nothing is written and
   * the warehouse repeats the callback.
   */
  @Override
  public void packed(String fulfilmentId, List<Parcel> parcels, byte[] manifest) {
    Optional<Fulfilment> current = fulfilments.find(fulfilmentId);
    if (current.isEmpty()) {
      throw new RetryLaterException("warehouse feedback for unknown fulfilment " + fulfilmentId);
    }
    if (!current.get().canPack()) {
      return;
    }
    Fulfilment snapshot = current.get();
    Instant now = clock.instant();
    String key =
        ClaimChecks.key(
            "fulfilment", snapshot.createdAt(), snapshot.orderId(), fulfilmentId, "json");
    ClaimCheck stored =
        documents.put(
            MANIFEST_BUCKET, key, manifest, "application/json", now.plus(MANIFEST_RETENTION));
    tx.executeWithoutResult(
        status ->
            onFulfilment(
                fulfilmentId,
                f -> f.pack(parcels, FulfilmentMessages.documentRef(stored), clock.instant())));
  }

  @Override
  @Transactional
  public void inspected(String returnId, Map<String, List<InspectionOutcome>> unitOutcomes) {
    Optional<ReturnIntake> found = intakes.findIntakeForUpdate(returnId);
    if (found.isEmpty()) {
      return;
    }
    ReturnIntake intake = found.get();
    Optional<Long> version = intake.inspect(unitOutcomes, clock.instant());
    if (version.isEmpty()) {
      return;
    }
    intakes.saveIntake(intake);
    outbox.append(
        FulfilmentMessages.returnInspected(intake, version.get()), Causation.root(returnId));
  }

  private void onFulfilment(
      String fulfilmentId,
      java.util.function.Function<Fulfilment, Optional<FulfilmentEvent>> change) {
    Optional<Fulfilment> found = fulfilments.findForUpdate(fulfilmentId);
    if (found.isEmpty()) {
      // The warehouse can answer before the submitting transaction commits: report it again later.
      throw new RetryLaterException("warehouse feedback for unknown fulfilment " + fulfilmentId);
    }
    Fulfilment f = found.get();
    Optional<FulfilmentEvent> e = change.apply(f);
    if (e.isEmpty()) {
      return; // a replayed callback, or progress after a cancel: ignored
    }
    fulfilments.save(f);
    // The flow's correlation id is the orderId; warehouse callbacks have no causing message.
    outbox.append(FulfilmentMessages.event(f, e.get()), Causation.root(f.orderId()));
  }
}
