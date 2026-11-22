package com.edacommerce.inventory.domain;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeMap;

/**
 * The reservation aggregate (ADR-0016): all-or-nothing hold with a TTL, committed after payment
 * authorisation, released as the saga's compensation. Every command is idempotent on the
 * reservationId: a repeated command re-emits the original reply and changes nothing (ADR-0006).
 * Pure: time comes in as a parameter, stock levels are passed in by the application.
 */
public record Reservation(
    String reservationId,
    String orderId,
    ReservationStatus status,
    List<StockLine> lines,
    Instant expiresAt,
    List<Shortage> shortages,
    String releaseReason,
    Instant changedAt,
    long version) {

  /** What a command does: the new state, the stock changes to apply, the reply to send. */
  public record Decision(Reservation reservation, List<StockEffect> effects, Reply reply, boolean changed) {
    static Decision replay(Reservation r) {
      return new Decision(r, List.of(), r.currentReply(), false);
    }
  }

  /** Sums quantities per SKU and orders by SKU (the lock order, so concurrent orders never deadlock). */
  public static List<StockLine> normalise(List<StockLine> lines) {
    Map<String, Integer> bySku = new TreeMap<>();
    for (StockLine l : lines) {
      bySku.merge(l.sku(), l.quantity(), Integer::sum);
    }
    List<StockLine> out = new ArrayList<>();
    bySku.forEach((sku, q) -> out.add(new StockLine(sku, q)));
    return List.copyOf(out);
  }

  /**
   * ReserveStock. {@code available} holds on_hand - reserved per SKU, read under row locks.
   *
   * @param existing the reservation with this id, if any (resend or a release that overtook us)
   * @param expired true if the command's envelope.expiresAt has passed: reject without acting
   */
  public static Decision reserve(
      Optional<Reservation> existing,
      String reservationId,
      String orderId,
      List<StockLine> requested,
      Duration ttl,
      Map<String, Integer> available,
      boolean expired,
      Instant now) {
    if (existing.isPresent()) {
      return Decision.replay(existing.get());
    }
    List<StockLine> lines = normalise(requested);
    if (lines.isEmpty()) {
      throw new InventoryException("reservation " + reservationId + " has no lines");
    }
    List<Shortage> shortages = new ArrayList<>();
    for (StockLine l : lines) {
      int free = Math.max(0, available.getOrDefault(l.sku(), 0));
      if (expired || free < l.quantity()) {
        shortages.add(new Shortage(l.sku(), l.quantity(), free));
      }
    }
    if (!shortages.isEmpty()) {
      Reservation r =
          new Reservation(reservationId, orderId, ReservationStatus.REJECTED, lines, now, List.copyOf(shortages), null, now, 1);
      return new Decision(r, List.of(), r.currentReply(), true);
    }
    Reservation r =
        new Reservation(reservationId, orderId, ReservationStatus.HELD, lines, now.plus(ttl), List.of(), null, now, 1);
    List<StockEffect> effects = lines.stream().<StockEffect>map(l -> new StockEffect.Reserve(l.sku(), l.quantity())).toList();
    return new Decision(r, effects, r.currentReply(), true);
  }

  /**
   * A release that arrives for a reservation we never saw (it overtook ReserveStock, or the reserve
   * was lost). A RELEASED tombstone makes a late ReserveStock with the same id a no-op.
   */
  public static Decision releaseUnknown(String reservationId, String orderId, String reason, Instant now) {
    Reservation r =
        new Reservation(reservationId, orderId, ReservationStatus.RELEASED, List.of(), now, List.of(), reason, now, 1);
    return new Decision(r, List.of(), r.currentReply(), true);
  }

  /** CommitReservation: a commit after the TTL is answered with ReservationExpired (§5.7). */
  public Decision commit(Instant now) {
    return switch (status) {
      case HELD -> {
        if (!now.isBefore(expiresAt)) {
          yield expire(now);
        }
        Reservation r = with(ReservationStatus.COMMITTED, null, now);
        yield new Decision(
            r, lines.stream().<StockEffect>map(l -> new StockEffect.Allocate(l.sku(), l.quantity())).toList(), r.currentReply(), true);
      }
      case COMMITTED, EXPIRED, RELEASED, REJECTED -> Decision.replay(this);
    };
  }

  /** ReleaseReservation: the compensation. Releasing twice is a no-op that repeats the reply. */
  public Decision release(String reason, Instant now) {
    return switch (status) {
      case HELD -> {
        Reservation r = with(ReservationStatus.RELEASED, reason, now);
        yield new Decision(
            r, lines.stream().<StockEffect>map(l -> new StockEffect.Unreserve(l.sku(), l.quantity())).toList(), r.currentReply(), true);
      }
      case COMMITTED -> {
        Reservation r = with(ReservationStatus.RELEASED, reason, now);
        yield new Decision(
            r, lines.stream().<StockEffect>map(l -> new StockEffect.Return(l.sku(), l.quantity())).toList(), r.currentReply(), true);
      }
      case RELEASED -> Decision.replay(this);
      // Nothing is held any more; confirm the compensation so the saga can finish.
      case EXPIRED, REJECTED -> new Decision(this, List.of(), new Reply.Released(reason, now), false);
    };
  }

  /** TTL expiry by the sweeper. Only held reservations expire. */
  public Decision expire(Instant now) {
    if (status != ReservationStatus.HELD) {
      return Decision.replay(this);
    }
    Reservation r = with(ReservationStatus.EXPIRED, null, now);
    return new Decision(
        r, lines.stream().<StockEffect>map(l -> new StockEffect.Unreserve(l.sku(), l.quantity())).toList(), r.currentReply(), true);
  }

  /** The reply that describes the current state, for resends. */
  public Reply currentReply() {
    return switch (status) {
      case HELD -> new Reply.Reserved(lines, expiresAt);
      case REJECTED -> new Reply.Rejected(shortages);
      case COMMITTED -> new Reply.Committed(changedAt);
      case RELEASED -> new Reply.Released(releaseReason == null ? "released" : releaseReason, changedAt);
      case EXPIRED -> new Reply.Expired(changedAt);
    };
  }

  private Reservation with(ReservationStatus next, String reason, Instant now) {
    return new Reservation(reservationId, orderId, next, lines, expiresAt, shortages, reason, now, version + 1);
  }
}
