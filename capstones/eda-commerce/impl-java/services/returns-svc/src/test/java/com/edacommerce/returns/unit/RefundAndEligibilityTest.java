package com.edacommerce.returns.unit;

import static com.edacommerce.returns.domain.InspectionOutcome.DAMAGED;
import static com.edacommerce.returns.domain.InspectionOutcome.MISSING;
import static com.edacommerce.returns.domain.InspectionOutcome.RESTOCKABLE;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.returns.domain.Eligibility;
import com.edacommerce.returns.domain.IneligibleReturnException;
import com.edacommerce.returns.domain.InspectedItem;
import com.edacommerce.returns.domain.OrderLine;
import com.edacommerce.returns.domain.RefundPolicy;
import com.edacommerce.returns.domain.ReturnItem;
import com.edacommerce.returns.domain.ReturnReason;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** The refund amount rule (architecture §6.2) and eligibility (returns.yaml 422). */
class RefundAndEligibilityTest {
  static final List<ReturnItem> ITEMS =
      List.of(new ReturnItem("l1", "SKU-1", 2, 1000), new ReturnItem("l2", "SKU-2", 1, 500));

  static RefundPolicy.Settlement settle(ReturnReason reason, boolean first, InspectedItem... r) {
    return RefundPolicy.settle(ITEMS, List.of(r), reason, first, 300);
  }

  @Test
  void restockableUnitsAreRefundedInFull() {
    RefundPolicy.Settlement s =
        settle(
            ReturnReason.OTHER,
            true,
            new InspectedItem("l1", "SKU-1", 2, RESTOCKABLE),
            new InspectedItem("l2", "SKU-2", 1, RESTOCKABLE));
    assertThat(s.amountMinor()).isEqualTo(2500);
    assertThat(s.partial()).isFalse();
    assertThat(s.restock()).containsExactly(Map.entry("SKU-1", 2), Map.entry("SKU-2", 1));
  }

  @Test
  void damagedUnitsAreRefundedOnlyForMerchantFaultAndMissingNever() {
    InspectedItem damaged = new InspectedItem("l1", "SKU-1", 2, DAMAGED);
    InspectedItem missing = new InspectedItem("l2", "SKU-2", 1, MISSING);
    assertThat(settle(ReturnReason.CHANGED_MIND, false, damaged, missing).amountMinor()).isZero();
    for (ReturnReason fault :
        List.of(ReturnReason.DAMAGED, ReturnReason.WRONG_ITEM, ReturnReason.NOT_AS_DESCRIBED)) {
      RefundPolicy.Settlement s = settle(fault, false, damaged, missing);
      assertThat(s.amountMinor()).isEqualTo(2000);
      assertThat(s.partial()).isTrue();
      assertThat(s.restock()).isEmpty();
    }
  }

  @Test
  void theShippingFeeIsRefundedForMerchantFaultOnTheFirstReturnOnly() {
    InspectedItem ok = new InspectedItem("l2", "SKU-2", 1, RESTOCKABLE);
    assertThat(settle(ReturnReason.WRONG_ITEM, true, ok).amountMinor()).isEqualTo(800);
    assertThat(settle(ReturnReason.WRONG_ITEM, false, ok).amountMinor()).isEqualTo(500);
    assertThat(settle(ReturnReason.CHANGED_MIND, true, ok).amountMinor()).isEqualTo(500);
  }

  @Test
  void unreportedUnitsAreMissing() {
    List<InspectedItem> all =
        RefundPolicy.complete(ITEMS, List.of(new InspectedItem("l1", "SKU-1", 1, RESTOCKABLE)));
    assertThat(all)
        .contains(
            new InspectedItem("l1", "SKU-1", 1, MISSING),
            new InspectedItem("l2", "SKU-2", 1, MISSING));
  }

  static final Instant NOW = Instant.parse("2026-11-20T09:00:00Z");
  static final List<OrderLine> ORDER =
      List.of(
          new OrderLine("l1", "SKU-1", "Mug", 2, 1000),
          new OrderLine("l2", "SKU-2", "Cup", 1, 500));

  static IneligibleReturnException.Reason refused(
      boolean delivered, Instant ends, Map<String, Integer> returned, Eligibility.Requested... r) {
    try {
      Eligibility.check(delivered, ends, ORDER, returned, List.of(r), NOW);
      return null;
    } catch (IneligibleReturnException e) {
      return e.reason();
    }
  }

  @Test
  void eligibilityRefusesWithAReason() {
    Instant open = NOW.plus(Duration.ofDays(5));
    assertThat(refused(false, null, Map.of(), new Eligibility.Requested("l1", 1)))
        .isEqualTo(IneligibleReturnException.Reason.NOT_DELIVERED);
    assertThat(refused(true, NOW.minusSeconds(1), Map.of(), new Eligibility.Requested("l1", 1)))
        .isEqualTo(IneligibleReturnException.Reason.WINDOW_CLOSED);
    assertThat(refused(true, open, Map.of(), new Eligibility.Requested("x", 1)))
        .isEqualTo(IneligibleReturnException.Reason.UNKNOWN_LINE);
    assertThat(refused(true, open, Map.of("l1", 1), new Eligibility.Requested("l1", 2)))
        .isEqualTo(IneligibleReturnException.Reason.QUANTITY_EXCEEDED);
    assertThat(
            refused(
                true,
                open,
                Map.of(),
                new Eligibility.Requested("l1", 1),
                new Eligibility.Requested("l1", 2)))
        .as("the same line twice counts once")
        .isEqualTo(IneligibleReturnException.Reason.QUANTITY_EXCEEDED);
    assertThat(refused(true, open, Map.of("l1", 1), new Eligibility.Requested("l1", 1))).isNull();
  }

  @Test
  void eligibleLinesArePricedFromTheOrder() {
    assertThat(
            Eligibility.check(
                true,
                NOW.plusSeconds(60),
                ORDER,
                Map.of(),
                List.of(new Eligibility.Requested("l2", 1)),
                NOW))
        .containsExactly(new ReturnItem("l2", "SKU-2", 1, 500));
    assertThat(Eligibility.returnable(ORDER, Map.of("l1", 2)))
        .containsExactly(Map.entry("l1", 0), Map.entry("l2", 1));
    assertThatThrownBy(() -> new ReturnItem("l", "s", 0, 1)).isInstanceOf(RuntimeException.class);
  }
}
