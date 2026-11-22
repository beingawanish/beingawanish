package com.edacommerce.fulfilment.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.fulfilment.domain.DocumentRef;
import com.edacommerce.fulfilment.domain.FailureReason;
import com.edacommerce.fulfilment.domain.Fulfilment;
import com.edacommerce.fulfilment.domain.FulfilmentEvent;
import com.edacommerce.fulfilment.domain.FulfilmentException;
import com.edacommerce.fulfilment.domain.FulfilmentStatus;
import com.edacommerce.fulfilment.domain.InspectionOutcome;
import com.edacommerce.fulfilment.domain.InspectionResult;
import com.edacommerce.fulfilment.domain.IntakeStatus;
import com.edacommerce.fulfilment.domain.OrderLine;
import com.edacommerce.fulfilment.domain.Parcel;
import com.edacommerce.fulfilment.domain.ParcelPlan;
import com.edacommerce.fulfilment.domain.ReturnIntake;
import com.edacommerce.fulfilment.domain.ReturnLine;
import com.edacommerce.fulfilment.domain.ShipTo;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

/** Layer 1: the fulfilment and returns-intake rules, pure and fast. */
class FulfilmentTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");
  static final ShipTo ADDRESS =
      new ShipTo("Ada", "Main St 1", null, "Berlin", null, "10115", "DE", null);
  static final List<OrderLine> LINES = List.of(new OrderLine("l1", "SKU-1", "Mug", 2));
  static final DocumentRef MANIFEST =
      new DocumentRef("packing-manifests", "k", "application/json", 10, "ab", T);

  static Fulfilment requested() {
    return Fulfilment.requested("f1", "o1", LINES, ADDRESS, "STANDARD", 1, T);
  }

  @Test
  void requestDecisionsFollowTheResendRules() {
    assertThat(Fulfilment.decideRequest(Optional.empty()))
        .isEqualTo(Fulfilment.RequestDecision.CREATE_AND_SUBMIT);
    Fulfilment f = requested();
    assertThat(Fulfilment.decideRequest(Optional.of(f)))
        .as("known but never acknowledged: push to the warehouse again")
        .isEqualTo(Fulfilment.RequestDecision.RESUBMIT);
    f.accept("wh", T, T);
    assertThat(Fulfilment.decideRequest(Optional.of(f)))
        .isEqualTo(Fulfilment.RequestDecision.ANSWER_ACCEPTED);
    f.pick(T);
    assertThat(Fulfilment.decideRequest(Optional.of(f)))
        .isEqualTo(Fulfilment.RequestDecision.ANSWER_ACCEPTED);
    assertThat(Fulfilment.decideRequest(Optional.of(Fulfilment.tombstone("f2", "o1", T))))
        .isEqualTo(Fulfilment.RequestDecision.ANSWER_CANCELLED);
    Fulfilment failed = requested();
    failed.fail(FailureReason.STOCK_DAMAGED, null, T);
    assertThat(Fulfilment.decideRequest(Optional.of(failed)))
        .isEqualTo(Fulfilment.RequestDecision.ANSWER_FAILED);
  }

  @Test
  void theHappyPathAdvancesTheVersionOncePerEvent() {
    Fulfilment f = requested();
    assertThat(f.accept("wh", T, T)).contains(new FulfilmentEvent.Accepted(1));
    assertThat(f.pick(T)).contains(new FulfilmentEvent.Picked(2));
    assertThat(f.pack(List.of(new Parcel("p1", 900, 1, 1, 1)), MANIFEST, T))
        .contains(new FulfilmentEvent.Packed(3));
    assertThat(f.dispatch("s1", T)).isEqualTo(new FulfilmentEvent.Dispatched(4));
    assertThat(f.status()).isEqualTo(FulfilmentStatus.DISPATCHED);
    assertThat(f.currentReply())
        .as("a late resend re-answers the original acceptance")
        .isEqualTo(new FulfilmentEvent.Accepted(1));
  }

  @Test
  void warehouseProgressOnlyMovesForwardAndNeverRevivesAStoppedOrder() {
    Fulfilment f = requested();
    assertThat(f.pick(T)).as("pick before accept").isEmpty();
    f.accept("wh", T, T);
    assertThat(f.accept("wh", T, T)).as("replayed callback").isEmpty();
    f.cancel(T);
    assertThat(f.pick(T)).isEmpty();
    assertThat(f.fail(FailureReason.STOCK_DAMAGED, null, T)).isEmpty();
    assertThat(f.canPack()).isFalse();
  }

  @Test
  void dispatchIsThePivotAndCannotBeCancelled() {
    Fulfilment f = requested();
    f.accept("wh", T, T);
    f.pick(T);
    f.pack(List.of(new Parcel("p1", 900, 1, 1, 1)), MANIFEST, T);
    assertThat(Fulfilment.decideCancel(Optional.of(f))).isEqualTo(Fulfilment.CancelDecision.CANCEL);
    f.dispatch("s1", T);
    assertThat(Fulfilment.decideCancel(Optional.of(f)))
        .isEqualTo(Fulfilment.CancelDecision.REFUSE_DISPATCHED);
    assertThatThrownBy(() -> f.cancel(T)).isInstanceOf(FulfilmentException.class);
    assertThat(Fulfilment.decideDispatch(Optional.of(f)))
        .isEqualTo(Fulfilment.DispatchDecision.ANSWER_DISPATCHED);
  }

  @Test
  void dispatchDecisions() {
    assertThat(Fulfilment.decideDispatch(Optional.empty()))
        .isEqualTo(Fulfilment.DispatchDecision.NOT_PACKED);
    assertThat(Fulfilment.decideDispatch(Optional.of(requested())))
        .isEqualTo(Fulfilment.DispatchDecision.NOT_PACKED);
    assertThat(Fulfilment.decideDispatch(Optional.of(Fulfilment.tombstone("f", "o", T))))
        .isEqualTo(Fulfilment.DispatchDecision.IGNORE_STOPPED);
    assertThat(Fulfilment.decideCancel(Optional.empty()))
        .isEqualTo(Fulfilment.CancelDecision.TOMBSTONE);
    assertThat(Fulfilment.decideCancel(Optional.of(Fulfilment.tombstone("f", "o", T))))
        .isEqualTo(Fulfilment.CancelDecision.ANSWER_CANCELLED);
  }

  @Test
  void aTombstoneAnswersCancelled() {
    Fulfilment t = Fulfilment.tombstone("f", "o", T);
    assertThat(t.currentReply()).isEqualTo(new FulfilmentEvent.Cancelled(1));
  }

  @Test
  void invalidLinesAreRejected() {
    assertThatThrownBy(() -> new OrderLine("l", "s", "n", 0))
        .isInstanceOf(FulfilmentException.class);
    assertThatThrownBy(() -> Fulfilment.requested("f", "o", List.of(), ADDRESS, "STANDARD", 1, T))
        .isInstanceOf(FulfilmentException.class);
  }

  @Test
  void parcelsAreSplitAtTwentyKilos() {
    assertThat(ParcelPlan.plan(LINES, i -> "p" + i))
        .containsExactly(new Parcel("p0", 900, 400, 300, 150));
    List<Parcel> big = ParcelPlan.plan(List.of(new OrderLine("l", "s", "n", 100)), i -> "p" + i);
    assertThat(big).hasSize(3);
    assertThat(big.stream().mapToInt(Parcel::weightGrams).sum()).isEqualTo(45_000);
    assertThat(big).allSatisfy(p -> assertThat(p.weightGrams()).isLessThanOrEqualTo(20_000));
  }

  @Test
  void anIntakeIsReceivedOnceAndInspectedOnceWithUnreportedUnitsMissing() {
    ReturnIntake r =
        ReturnIntake.expect(
            "r1",
            "o1",
            "RMA-2026-000001",
            List.of(new ReturnLine("l1", "SKU-1", 3), new ReturnLine("l2", "SKU-2", 1)),
            T);
    assertThat(r.inspect(Map.of(), T)).as("not received yet").isEmpty();
    assertThat(r.receive(T)).contains(1L);
    assertThat(r.receive(T)).as("duplicate delivery notice").isEmpty();
    assertThat(
            r.inspect(
                Map.of("l1", List.of(InspectionOutcome.DAMAGED, InspectionOutcome.RESTOCKABLE)), T))
        .contains(2L);
    assertThat(r.status()).isEqualTo(IntakeStatus.INSPECTED);
    assertThat(r.results())
        .containsExactly(
            new InspectionResult("l1", "SKU-1", 1, InspectionOutcome.RESTOCKABLE, null),
            new InspectionResult("l1", "SKU-1", 1, InspectionOutcome.DAMAGED, null),
            new InspectionResult("l1", "SKU-1", 1, InspectionOutcome.MISSING, null),
            new InspectionResult("l2", "SKU-2", 1, InspectionOutcome.MISSING, null));
    assertThat(r.inspect(Map.of(), T)).isEmpty();
  }

  @Test
  void extraReportedUnitsAreIgnored() {
    assertThat(
            ReturnIntake.group(
                new ReturnLine("l", "s", 1),
                List.of(InspectionOutcome.RESTOCKABLE, InspectionOutcome.DAMAGED)))
        .containsExactly(new InspectionResult("l", "s", 1, InspectionOutcome.RESTOCKABLE, null));
  }

  @Test
  void theAddressIsNeverPrinted() {
    assertThat(ADDRESS.toString()).doesNotContain("Ada").doesNotContain("Main");
  }
}
