package com.edacommerce.returns.domain;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * Return eligibility (returns.yaml): delivered, inside the window, quantities not already returned.
 * Checked synchronously against returns-svc's own projection, so the customer gets a clear yes or
 * no at once. Pure.
 */
public final class Eligibility {
  private Eligibility() {}

  /** A requested line. */
  public record Requested(String lineId, int quantity) {}

  /**
   * @param alreadyReturned quantity per lineId held by earlier returns of the order
   * @return the requested lines, priced from the order
   */
  public static List<ReturnItem> check(
      boolean delivered,
      Instant windowEndsAt,
      List<OrderLine> orderLines,
      Map<String, Integer> alreadyReturned,
      List<Requested> requested,
      Instant now) {
    if (!delivered || windowEndsAt == null) {
      throw new IneligibleReturnException(
          IneligibleReturnException.Reason.NOT_DELIVERED, "the order has not been delivered yet");
    }
    if (now.isAfter(windowEndsAt)) {
      throw new IneligibleReturnException(
          IneligibleReturnException.Reason.WINDOW_CLOSED,
          "the return window closed at " + windowEndsAt);
    }
    Map<String, OrderLine> byId = new HashMap<>();
    orderLines.forEach(l -> byId.put(l.lineId(), l));
    Map<String, Integer> asked = new HashMap<>();
    List<ReturnItem> items = new ArrayList<>();
    for (Requested r : requested) {
      OrderLine line = byId.get(r.lineId());
      if (line == null) {
        throw new IneligibleReturnException(
            IneligibleReturnException.Reason.UNKNOWN_LINE,
            "no line " + r.lineId() + " in the order");
      }
      int total = asked.merge(r.lineId(), r.quantity(), Integer::sum);
      int left = line.quantity() - alreadyReturned.getOrDefault(r.lineId(), 0);
      if (total > left) {
        throw new IneligibleReturnException(
            IneligibleReturnException.Reason.QUANTITY_EXCEEDED,
            "line " + r.lineId() + " has " + Math.max(left, 0) + " left to return");
      }
      items.add(new ReturnItem(line.lineId(), line.sku(), r.quantity(), line.unitPriceMinor()));
    }
    if (items.isEmpty()) {
      throw new ReturnsException("a return needs at least one line");
    }
    return List.copyOf(items);
  }

  /** What is still returnable per line. */
  public static Map<String, Integer> returnable(
      List<OrderLine> orderLines, Map<String, Integer> alreadyReturned) {
    Map<String, Integer> out = new java.util.LinkedHashMap<>();
    for (OrderLine l : orderLines) {
      out.put(l.lineId(), Math.max(0, l.quantity() - alreadyReturned.getOrDefault(l.lineId(), 0)));
    }
    return out;
  }
}
