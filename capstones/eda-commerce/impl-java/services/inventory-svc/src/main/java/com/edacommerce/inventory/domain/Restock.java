package com.edacommerce.inventory.domain;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

/** RestockItems from the returns saga, idempotent on restockId (ADR-0016). */
public record Restock(
    String restockId, String orderId, String returnId, List<StockLine> lines, Instant restockedAt) {

  /** The restock to record and its stock effects; empty effects when it is a resend. */
  public record Decision(Restock restock, List<StockEffect> effects, boolean changed) {}

  public static Decision apply(
      Optional<Restock> existing,
      String restockId,
      String orderId,
      String returnId,
      List<StockLine> lines,
      Instant now) {
    if (existing.isPresent()) {
      return new Decision(existing.get(), List.of(), false);
    }
    List<StockLine> normalised = Reservation.normalise(lines);
    return new Decision(
        new Restock(restockId, orderId, returnId, normalised, now),
        normalised.stream()
            .<StockEffect>map(l -> new StockEffect.Return(l.sku(), l.quantity()))
            .toList(),
        true);
  }
}
