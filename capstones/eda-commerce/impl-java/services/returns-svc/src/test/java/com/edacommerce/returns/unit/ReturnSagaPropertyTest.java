package com.edacommerce.returns.unit;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.returns.domain.InspectionOutcome;
import com.edacommerce.returns.domain.ReturnEvent;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnSagaCommand;
import com.edacommerce.returns.domain.ReturnSagaState;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import com.edacommerce.returns.domain.ReturnSagaTrigger.Decision.Kind;
import java.time.Duration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import net.jqwik.api.constraints.IntRange;
import net.jqwik.api.constraints.Size;

/**
 * Random interleavings of replies, duplicates, deadlines and decisions always end closed or with a
 * human; every refund command for a return carries one refundId and never exceeds what the customer
 * paid; nothing is emitted after CLOSED; versions strictly increase.
 */
class ReturnSagaPropertyTest {
  static final int KINDS = 12;

  @Property(tries = 1000)
  void everyInterleavingSettlesConsistently(
      @ForAll @Size(max = 40) List<@IntRange(min = 0, max = KINDS - 1) Integer> script,
      @ForAll boolean merchantFault) {
    ReturnRun r =
        ReturnRun.started(merchantFault ? ReturnReason.DAMAGED : ReturnReason.CHANGED_MIND);
    for (int k : script) {
      if (r.state == ReturnSagaState.CLOSED) {
        int before = r.decisions.size();
        r.on(trigger(r, k));
        assertThat(r.decisions).as("nothing happens after CLOSED").hasSize(before);
        continue;
      }
      r.on(trigger(r, k));
    }
    // Drain: the parcel arrives, participants answer, time passes.
    for (int i = 0; i < 30 && r.state != ReturnSagaState.CLOSED && !r.state.attention(); i++) {
      switch (r.state) {
        case AWAITING_PARCEL -> r.received();
        case AWAITING_INSPECTION -> r.inspected(ReturnRun.item(2, InspectionOutcome.RESTOCKABLE));
        case SETTLING -> {
          if (!r.data.restocked) {
            r.on(new ReturnSagaTrigger.ItemsRestocked(r.data.restockId));
          } else {
            r.on(new ReturnSagaTrigger.RefundSucceeded(r.data.refundId));
          }
        }
        default -> r.advance(Duration.ofDays(1));
      }
    }
    assertThat(r.state == ReturnSagaState.CLOSED || r.state.attention()).isTrue();

    Set<String> refundIds = new HashSet<>();
    long maxRefund = 2 * 12_999 + 499;
    long lastVersion = 0;
    for (var d : r.decisions) {
      for (var c : d.commands()) {
        if (c instanceof ReturnSagaCommand.RefundPayment p) {
          refundIds.add(p.refundId());
          assertThat(p.amountMinor()).isPositive().isLessThanOrEqualTo(maxRefund);
        }
      }
      for (ReturnEvent e : d.events()) {
        assertThat(e.version()).isGreaterThan(lastVersion);
        lastVersion = e.version();
      }
    }
    assertThat(refundIds).hasSizeLessThanOrEqualTo(1);
    if (r.state == ReturnSagaState.CLOSED && r.data.outcome != null) {
      assertThat(r.data.outcome.name())
          .isIn("REFUNDED", "PARTIALLY_REFUNDED", "REJECTED", "EXPIRED", "MANUAL_REVIEW");
    }
  }

  static ReturnSagaTrigger trigger(ReturnRun r, int k) {
    return switch (k) {
      case 0 -> new ReturnSagaTrigger.ParcelReceived();
      case 1 ->
          new ReturnSagaTrigger.Inspected(
              List.of(ReturnRun.item(2, InspectionOutcome.RESTOCKABLE)));
      case 2 ->
          new ReturnSagaTrigger.Inspected(
              List.of(
                  ReturnRun.item(1, InspectionOutcome.RESTOCKABLE),
                  ReturnRun.item(1, InspectionOutcome.DAMAGED)));
      case 3 ->
          new ReturnSagaTrigger.ItemsRestocked(r.data.restockId == null ? "x" : r.data.restockId);
      case 4 ->
          new ReturnSagaTrigger.RefundSucceeded(r.data.refundId == null ? "x" : r.data.refundId);
      case 5 ->
          new ReturnSagaTrigger.RefundFailed(
              r.data.refundId == null ? "x" : r.data.refundId, true, "e");
      case 6 ->
          new ReturnSagaTrigger.RefundFailed(
              r.data.refundId == null ? "x" : r.data.refundId, false, "e");
      case 7 -> {
        r.advance(Duration.ofHours(2));
        yield new ReturnSagaTrigger.Deadline();
      }
      case 8 -> {
        r.advance(Duration.ofDays(15));
        yield new ReturnSagaTrigger.Deadline();
      }
      case 9 -> new ReturnSagaTrigger.Decision(Kind.RETRY_REFUND, null);
      case 10 -> new ReturnSagaTrigger.OperatorRetry();
      default ->
          new ReturnSagaTrigger.Inspected(List.of(ReturnRun.item(2, InspectionOutcome.DAMAGED)));
    };
  }
}
