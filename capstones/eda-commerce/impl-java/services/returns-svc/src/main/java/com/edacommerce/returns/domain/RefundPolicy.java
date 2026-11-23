package com.edacommerce.returns.domain;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * The refund amount rule (architecture §6.2), in the returns domain, not in payment:
 *
 * <ul>
 *   <li>RESTOCKABLE units: full unit price.
 *   <li>DAMAGED units: full unit price for merchant-fault reasons (DAMAGED, WRONG_ITEM,
 *       NOT_AS_DESCRIBED), zero otherwise.
 *   <li>MISSING units: zero.
 *   <li>Shipping fee: only for merchant-fault reasons, only on the first return of the order.
 * </ul>
 *
 * A refund is partial when any inspected unit was refunded below its price.
 */
public final class RefundPolicy {
  private RefundPolicy() {}

  /** The outcome of the rule. {@code restock}: sku -> quantity going back on the shelf. */
  public record Settlement(long amountMinor, boolean partial, Map<String, Integer> restock) {}

  public static Settlement settle(
      List<ReturnItem> items,
      List<InspectedItem> inspected,
      ReturnReason reason,
      boolean firstReturn,
      long shippingFeeMinor) {
    Map<String, Long> unitPrice = new HashMap<>();
    items.forEach(i -> unitPrice.put(i.lineId(), i.unitPriceMinor()));
    long amount = 0;
    boolean partial = false;
    Map<String, Integer> restock = new LinkedHashMap<>();
    for (InspectedItem r : inspected) {
      Long price = unitPrice.get(r.lineId());
      if (price == null) {
        throw new ReturnsException("inspection reported line " + r.lineId() + " not in the return");
      }
      boolean refunded =
          switch (r.outcome()) {
            case RESTOCKABLE -> true;
            case DAMAGED -> reason.merchantFault();
            case MISSING -> false;
          };
      if (refunded) {
        amount = Math.addExact(amount, Math.multiplyExact(price, r.quantity()));
      } else {
        partial = true;
      }
      if (r.outcome() == InspectionOutcome.RESTOCKABLE) {
        restock.merge(r.sku(), r.quantity(), Integer::sum);
      }
    }
    if (amount > 0 && reason.merchantFault() && firstReturn) {
      amount = Math.addExact(amount, Math.max(0, shippingFeeMinor));
    }
    return new Settlement(amount, partial, restock);
  }

  /** Lines the warehouse did not mention are MISSING. */
  public static List<InspectedItem> complete(List<ReturnItem> items, List<InspectedItem> reported) {
    Map<String, Integer> seen = new HashMap<>();
    reported.forEach(r -> seen.merge(r.lineId(), r.quantity(), Integer::sum));
    List<InspectedItem> out = new ArrayList<>(reported);
    for (ReturnItem i : items) {
      int missing = i.quantity() - seen.getOrDefault(i.lineId(), 0);
      if (missing > 0) {
        out.add(new InspectedItem(i.lineId(), i.sku(), missing, InspectionOutcome.MISSING));
      }
    }
    return List.copyOf(out);
  }
}
