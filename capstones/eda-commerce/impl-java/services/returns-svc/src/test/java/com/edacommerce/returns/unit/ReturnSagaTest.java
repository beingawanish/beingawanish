package com.edacommerce.returns.unit;

import static com.edacommerce.returns.domain.InspectionOutcome.DAMAGED;
import static com.edacommerce.returns.domain.InspectionOutcome.RESTOCKABLE;
import static com.edacommerce.returns.domain.ReturnSagaState.*;
import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.returns.domain.LabelRef;
import com.edacommerce.returns.domain.ReturnEvent;
import com.edacommerce.returns.domain.ReturnItem;
import com.edacommerce.returns.domain.ReturnOutcome;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnSagaCommand;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import com.edacommerce.returns.domain.ReturnSagaTrigger.Decision.Kind;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/** Every transition of architecture §6.1, plus late, duplicate and out-of-order replies. */
class ReturnSagaTest {
  static final LabelRef LABEL =
      new LabelRef("shipping-labels", "k", "application/pdf", 1, "ab", null);

  static ReturnRun awaitingInspection(ReturnReason reason) {
    ReturnRun r = ReturnRun.started(reason);
    r.received();
    return r;
  }

  @Test
  void aSmallReturnIsAuthorizedAndTheLabelAndIntakeAreRequested() {
    ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
    assertThat(r.path).containsExactly(REQUESTED, AUTHORIZED, AWAITING_PARCEL);
    assertThat(r.data.rmaNumber).isEqualTo("RMA-2026-000001");
    assertThat(r.data.parcelDueBy).isEqualTo(ReturnRun.T0.plus(Duration.ofDays(14)));
    assertThat(r.eventsSince(0))
        .containsExactly(new ReturnEvent.Requested(1), new ReturnEvent.Authorized(2));
    assertThat(r.commandsSince(0))
        .containsExactly(
            new ReturnSagaCommand.IssueReturnLabel(r.data.shipmentId),
            new ReturnSagaCommand.ExpectReturn(r.data.parcelDueBy));
    assertThat(r.deadline).isEqualTo(r.data.parcelDueBy);
  }

  @Nested
  class ManualReview {
    ReturnRun highValue() {
      return ReturnRun.started(
          ReturnReason.CHANGED_MIND, List.of(new ReturnItem("l1", "SKU-1", 1, 50_001)));
    }

    @Test
    void aReturnAboveTheLimitWaitsForAHuman() {
      ReturnRun r = highValue();
      assertThat(r.state).isEqualTo(MANUAL_REVIEW);
      assertThat(r.last.attention()).isTrue();
      assertThat(r.deadline).isNull();
      assertThat(r.on(new ReturnSagaTrigger.Decision(Kind.RETRY_REFUND, null)))
          .as("not a decision this state waits for")
          .isFalse();
    }

    @Test
    void approveAuthorizes() {
      ReturnRun r = highValue();
      r.on(new ReturnSagaTrigger.Decision(Kind.APPROVE, "ok"));
      assertThat(r.path).containsSubsequence(MANUAL_REVIEW, AUTHORIZED, AWAITING_PARCEL);
      assertThat(r.data.rmaNumber).isNotNull();
    }

    @Test
    void rejectClosesAsRejected() {
      ReturnRun r = highValue();
      int from = r.decisions.size();
      r.on(new ReturnSagaTrigger.Decision(Kind.REJECT, "worn"));
      assertThat(r.path).containsSubsequence(MANUAL_REVIEW, REJECTED, CLOSED);
      assertThat(r.eventsSince(from))
          .containsExactly(
              new ReturnEvent.Rejected(2, "worn"),
              new ReturnEvent.Closed(3, ReturnOutcome.REJECTED));
      assertThat(r.last.terminal()).isTrue();
      assertThat(r.commandsSince(from)).isEmpty();
    }
  }

  @Nested
  class AwaitingParcel {
    @Test
    void theLabelIsStoredOnceAndOnlyForOurShipment() {
      ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
      assertThat(r.on(new ReturnSagaTrigger.LabelIssued("other", LABEL))).isFalse();
      assertThat(r.on(new ReturnSagaTrigger.LabelIssued(r.data.shipmentId, LABEL))).isTrue();
      assertThat(r.state).isEqualTo(AWAITING_PARCEL);
      assertThat(r.data.label).isEqualTo(LABEL);
      assertThat(r.on(new ReturnSagaTrigger.LabelIssued(r.data.shipmentId, LABEL))).isFalse();
    }

    @Test
    void theParcelDeadlineExpiresTheReturn() {
      ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
      r.advance(Duration.ofDays(13));
      assertThat(r.on(new ReturnSagaTrigger.Deadline())).as("not due yet").isFalse();
      r.advance(Duration.ofDays(2));
      int from = r.decisions.size();
      r.on(new ReturnSagaTrigger.Deadline());
      assertThat(r.path).containsSubsequence(AWAITING_PARCEL, EXPIRED, CLOSED);
      assertThat(r.decisions.get(from).timeout()).isTrue();
      assertThat(r.eventsSince(from))
          .containsExactly(new ReturnEvent.Closed(3, ReturnOutcome.EXPIRED));
      assertThat(r.on(new ReturnSagaTrigger.ParcelReceived())).as("late parcel").isFalse();
    }

    @Test
    void receivedThenInspectedOnceEach() {
      ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
      r.received();
      assertThat(r.state).isEqualTo(AWAITING_INSPECTION);
      assertThat(r.deadline).isNull();
      assertThat(r.on(new ReturnSagaTrigger.ParcelReceived())).isFalse();
    }

    @Test
    void anInspectionOvertakingTheReceiptIsApplied() {
      ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      assertThat(r.state).isEqualTo(SETTLING);
      assertThat(r.data.received).isTrue();
      assertThat(r.on(new ReturnSagaTrigger.ParcelReceived())).isFalse();
    }

    @Test
    void theOperatorCanResendTheLabelCommands() {
      ReturnRun r = ReturnRun.started(ReturnReason.CHANGED_MIND);
      int from = r.decisions.size();
      r.on(new ReturnSagaTrigger.OperatorRetry());
      assertThat(r.commandsSince(from))
          .containsExactly(
              new ReturnSagaCommand.IssueReturnLabel(r.data.shipmentId),
              new ReturnSagaCommand.ExpectReturn(r.data.parcelDueBy));
    }
  }

  @Nested
  class Settling {
    @Test
    void aFullyRestockableReturnRefundsTheLineTotalAndRestocks() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      int from = r.decisions.size();
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      assertThat(r.state).isEqualTo(SETTLING);
      assertThat(r.commandsSince(from))
          .containsExactly(
              new ReturnSagaCommand.RestockItems(r.data.restockId, Map.of("SKU-1001", 2)),
              new ReturnSagaCommand.RefundPayment(r.data.refundId, 25_998));
      r.on(new ReturnSagaTrigger.RefundSucceeded(r.data.refundId));
      assertThat(r.state).as("still waiting for the restock").isEqualTo(SETTLING);
      int last = r.decisions.size();
      r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId));
      assertThat(r.state).isEqualTo(CLOSED);
      assertThat(r.eventsSince(last))
          .containsExactly(
              new ReturnEvent.Refunded(3), new ReturnEvent.Closed(4, ReturnOutcome.REFUNDED));
      assertThat(r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId))).isFalse();
    }

    @Test
    void oneDamagedItemWithChangedMindIsAPartialRefund() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(1, RESTOCKABLE), ReturnRun.item(1, DAMAGED));
      assertThat(r.data.refundAmountMinor).isEqualTo(12_999);
      assertThat(r.data.restock).containsExactly(Map.entry("SKU-1001", 1));
      r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId));
      r.on(new ReturnSagaTrigger.RefundSucceeded(r.data.refundId));
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.PARTIALLY_REFUNDED);
    }

    @Test
    void nothingRefundableIsRejectedAfterInspection() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      int from = r.decisions.size();
      r.inspected(ReturnRun.item(2, DAMAGED));
      assertThat(r.path).containsSubsequence(AWAITING_INSPECTION, REJECTED, CLOSED);
      assertThat(r.commandsSince(from)).isEmpty();
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.REJECTED);
    }

    @Test
    void merchantFaultRefundsDamagedItemsAndTheShippingFee() {
      ReturnRun r = awaitingInspection(ReturnReason.DAMAGED);
      r.inspected(ReturnRun.item(2, DAMAGED));
      assertThat(r.state).isEqualTo(SETTLING);
      assertThat(r.data.refundAmountMinor).isEqualTo(25_998 + 499);
      assertThat(r.data.restockId).as("damaged goods are not restocked").isNull();
      r.on(new ReturnSagaTrigger.RefundSucceeded(r.data.refundId));
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.REFUNDED);
    }

    @Test
    void retryableRefundFailuresAreResentOnTheScheduleWithTheSameRefundIdThenReviewed() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId));
      String refundId = r.data.refundId;
      for (Duration wait :
          List.of(Duration.ofMinutes(1), Duration.ofMinutes(10), Duration.ofHours(1))) {
        r.on(new ReturnSagaTrigger.RefundFailed(refundId, true, "psp"));
        assertThat(r.state).isEqualTo(SETTLING);
        assertThat(r.deadline).isEqualTo(r.now.plus(wait));
        r.advance(wait);
        int from = r.decisions.size();
        r.on(new ReturnSagaTrigger.Deadline());
        assertThat(r.commandsSince(from))
            .containsExactly(new ReturnSagaCommand.RefundPayment(refundId, 25_998));
      }
      r.on(new ReturnSagaTrigger.RefundFailed(refundId, true, "psp"));
      assertThat(r.state).isEqualTo(REFUND_REVIEW);
      assertThat(r.last.attention()).isTrue();

      int from = r.decisions.size();
      r.on(new ReturnSagaTrigger.Decision(Kind.RETRY_REFUND, null));
      assertThat(r.state).isEqualTo(SETTLING);
      assertThat(r.commandsSince(from))
          .containsExactly(new ReturnSagaCommand.RefundPayment(refundId, 25_998));
      r.on(new ReturnSagaTrigger.RefundSucceeded(refundId));
      assertThat(r.state).isEqualTo(CLOSED);
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.REFUNDED);
    }

    @Test
    void aNonRetryableFailureGoesStraightToReviewWhereStaffCanCloseWithoutRefund() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      r.on(new ReturnSagaTrigger.RefundFailed(r.data.refundId, false, "card closed"));
      assertThat(r.state).isEqualTo(REFUND_REVIEW);
      assertThat(r.on(new ReturnSagaTrigger.Decision(Kind.APPROVE, null))).isFalse();
      r.on(new ReturnSagaTrigger.Decision(Kind.CLOSE_WITHOUT_REFUND, "paid by bank transfer"));
      assertThat(r.state).isEqualTo(CLOSED);
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.MANUAL_REVIEW);
    }

    @Test
    void aFailedRefundThatSucceededAfterAllClosesWithoutAHuman() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId));
      r.on(new ReturnSagaTrigger.RefundFailed(r.data.refundId, false, "timeout"));
      r.on(new ReturnSagaTrigger.RefundSucceeded(r.data.refundId));
      assertThat(r.path).containsSubsequence(REFUND_REVIEW, CLOSED);
      assertThat(r.data.outcome).isEqualTo(ReturnOutcome.REFUNDED);
    }

    @Test
    void lostRepliesAreChasedOnTheDeadline() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      r.advance(Duration.ofMinutes(11));
      int from = r.decisions.size();
      r.on(new ReturnSagaTrigger.Deadline());
      assertThat(r.commandsSince(from))
          .containsExactly(
              new ReturnSagaCommand.RestockItems(r.data.restockId, Map.of("SKU-1001", 2)),
              new ReturnSagaCommand.RefundPayment(r.data.refundId, 25_998));
      assertThat(r.attempts).isEqualTo(1);
    }

    @Test
    void repliesForOtherIdsAreIgnored() {
      ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
      r.inspected(ReturnRun.item(2, RESTOCKABLE));
      assertThat(r.on(new ReturnSagaTrigger.RefundSucceeded("other"))).isFalse();
      assertThat(r.on(new ReturnSagaTrigger.ItemsRestocked("other"))).isFalse();
      assertThat(r.on(new ReturnSagaTrigger.RefundFailed("other", true, "x"))).isFalse();
    }
  }

  @Test
  void aClosedReturnIgnoresEverything() {
    ReturnRun r = awaitingInspection(ReturnReason.CHANGED_MIND);
    r.inspected(ReturnRun.item(2, DAMAGED));
    assertThat(r.state).isEqualTo(CLOSED);
    assertThat(r.on(new ReturnSagaTrigger.OperatorRetry())).isFalse();
    assertThat(r.on(new ReturnSagaTrigger.Deadline())).isFalse();
    assertThat(r.on(new ReturnSagaTrigger.Decision(Kind.APPROVE, null))).isFalse();
  }
}
