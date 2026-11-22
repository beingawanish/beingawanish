package com.edacommerce.inventory.application;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import com.edacommerce.inventory.domain.Reservation;
import com.edacommerce.inventory.domain.Restock;
import com.edacommerce.inventory.domain.StockEffect;
import com.edacommerce.inventory.domain.StockLevel;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.TreeSet;
import org.springframework.transaction.annotation.Transactional;

/**
 * Inventory's use cases. Each runs in one transaction (the consumer's, when called from a handler):
 * lock the affected rows, let the domain decide, apply stock effects with conditional updates, save
 * the reservation, append the reply and the new stock levels to the outbox.
 */
public class InventoryUseCases {
  private final ReservationRepository reservations;
  private final StockRepository stock;
  private final RestockRepository restocks;
  private final OutboxWriter outbox;
  private final Clock clock;
  private final Duration maxTtl;

  public InventoryUseCases(
      ReservationRepository reservations,
      StockRepository stock,
      RestockRepository restocks,
      OutboxWriter outbox,
      Clock clock,
      Duration maxTtl) {
    this.reservations = reservations;
    this.stock = stock;
    this.restocks = restocks;
    this.outbox = outbox;
    this.clock = clock;
    this.maxTtl = maxTtl;
  }

  /**
   * ReserveStock. The TTL is the command's, capped by RESERVATION_TTL (the drill in architecture
   * §5.7 shortens it on inventory-svc alone).
   */
  @Transactional
  public Reservation.Decision reserve(
      String orderId, String reservationId, List<StockLine> lines, int ttlSeconds, boolean commandExpired, Causation causation) {
    Instant now = clock.instant();
    Optional<Reservation> existing = reservations.findForUpdate(reservationId);
    Map<String, Integer> available = new LinkedHashMap<>();
    if (existing.isEmpty()) {
      TreeSet<String> skus = new TreeSet<>();
      lines.forEach(l -> skus.add(l.sku()));
      stock.lockAll(skus).forEach((sku, level) -> available.put(sku, level.available()));
    }
    Duration ttl = Duration.ofSeconds(Math.max(1, ttlSeconds));
    if (ttl.compareTo(maxTtl) > 0) {
      ttl = maxTtl;
    }
    Reservation.Decision d =
        Reservation.reserve(existing, reservationId, orderId, lines, ttl, available, commandExpired, now);
    return finish(d, causation, now);
  }

  @Transactional
  public Optional<Reservation.Decision> commit(String reservationId, Causation causation) {
    Instant now = clock.instant();
    return reservations.findForUpdate(reservationId).map(r -> finish(lockAnd(r).commit(now), causation, now));
  }

  @Transactional
  public Reservation.Decision release(String orderId, String reservationId, String reason, Causation causation) {
    Instant now = clock.instant();
    Reservation.Decision d =
        reservations
            .findForUpdate(reservationId)
            .map(r -> lockAnd(r).release(reason, now))
            .orElseGet(() -> Reservation.releaseUnknown(reservationId, orderId, reason, now));
    return finish(d, causation, now);
  }

  @Transactional
  public Restock.Decision restock(
      String orderId, String returnId, String restockId, List<StockLine> lines, Causation causation) {
    Instant now = clock.instant();
    Optional<Restock> existing = restocks.find(restockId);
    if (existing.isEmpty()) {
      TreeSet<String> skus = new TreeSet<>();
      lines.forEach(l -> skus.add(l.sku()));
      Map<String, StockLevel> locked = stock.lockAll(skus);
      for (String sku : skus) {
        if (!locked.containsKey(sku)) {
          stock.setOnHand(sku, 0);
        }
      }
    }
    Restock.Decision d = Restock.apply(existing, restockId, orderId, returnId, lines, now);
    d.effects().forEach(stock::apply);
    if (d.changed()) {
      restocks.save(d.restock());
    }
    outbox.append(InventoryMessages.restocked(d.restock()), causation);
    publishLevels(d.effects(), causation, now);
    return d;
  }

  /** Expires due reservations (sweeper). Returns how many expired. */
  @Transactional
  public int expireDue(int limit) {
    Instant now = clock.instant();
    List<String> due = reservations.lockExpired(now, limit);
    int n = 0;
    for (String id : due) {
      Optional<Reservation> r = reservations.findForUpdate(id);
      if (r.isPresent()) {
        Reservation.Decision d = lockAnd(r.get()).expire(now);
        if (d.changed()) {
          finish(d, Causation.root(r.get().orderId()), now);
          n++;
        }
      }
    }
    return n;
  }

  @Transactional
  public StockLevel setStock(String sku, int onHand) {
    stock.lockAll(List.of(sku));
    StockLevel level = stock.setOnHand(sku, onHand);
    outbox.append(InventoryMessages.stockLevel(level, clock.instant()), Causation.root(sku));
    return level;
  }

  private Reservation lockAnd(Reservation r) {
    TreeSet<String> skus = new TreeSet<>();
    r.lines().forEach(l -> skus.add(l.sku()));
    stock.lockAll(skus);
    return r;
  }

  private Reservation.Decision finish(Reservation.Decision d, Causation causation, Instant now) {
    d.effects().forEach(stock::apply);
    if (d.changed()) {
      reservations.save(d.reservation());
    }
    outbox.append(InventoryMessages.reply(d.reservation(), d.reply()), causation);
    publishLevels(d.effects(), causation, now);
    return d;
  }

  private void publishLevels(List<StockEffect> effects, Causation causation, Instant now) {
    TreeSet<String> skus = new TreeSet<>();
    effects.forEach(e -> skus.add(e.sku()));
    for (String sku : skus) {
      stock.find(sku).ifPresent(level -> outbox.append(InventoryMessages.stockLevel(level, now), causation));
    }
  }
}
