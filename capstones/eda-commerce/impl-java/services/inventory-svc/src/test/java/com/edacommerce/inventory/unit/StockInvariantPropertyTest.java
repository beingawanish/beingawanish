package com.edacommerce.inventory.unit;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.inventory.domain.Reservation;
import com.edacommerce.inventory.domain.ReservationStatus;
import com.edacommerce.inventory.domain.StockEffect;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Duration;
import java.time.Instant;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import net.jqwik.api.constraints.IntRange;
import net.jqwik.api.constraints.Size;

/** Any interleaving of reserve/commit/release/expire keeps stock non-negative and consistent. */
class StockInvariantPropertyTest {
  static final Instant T0 = Instant.parse("2026-11-18T09:00:00Z");

  @Property(tries = 300)
  void stockNeverGoesNegativeAndReservedMatchesHeldLines(
      @ForAll @Size(min = 1, max = 40) List<@IntRange(min = 0, max = 59) Integer> ops,
      @ForAll @IntRange(min = 0, max = 6) int initial) {
    Map<String, int[]> stock = new HashMap<>(); // sku -> {onHand, reserved}
    stock.put("A", new int[] {initial, 0});
    stock.put("B", new int[] {initial, 0});
    Map<String, Reservation> reservations = new HashMap<>();
    Instant now = T0;
    for (int op : ops) {
      String id = "r" + (op % 5);
      now = now.plusSeconds(op % 7 == 0 ? 600 : 1);
      Optional<Reservation> existing = Optional.ofNullable(reservations.get(id));
      final Instant at = now;
      Reservation.Decision d =
          switch ((op / 5) % 4) {
            case 0 -> Reservation.reserve(existing, id, "o", List.of(new StockLine("A", 1 + op % 2), new StockLine("B", 1)),
                Duration.ofMinutes(15), available(stock), false, now);
            case 1 -> existing.map(r -> r.commit(at)).orElse(null);
            case 2 -> existing.map(r -> r.release("x", at)).orElse(null);
            default -> existing.map(r -> r.expire(at)).orElse(null);
          };
      if (d == null) {
        continue;
      }
      for (StockEffect e : d.effects()) {
        int[] s = stock.get(e.sku());
        switch (e) {
          case StockEffect.Reserve r -> s[1] += r.quantity();
          case StockEffect.Unreserve u -> s[1] -= u.quantity();
          case StockEffect.Allocate a -> {
            s[0] -= a.quantity();
            s[1] -= a.quantity();
          }
          case StockEffect.Return r -> s[0] += r.quantity();
        }
        assertThat(s[0]).isGreaterThanOrEqualTo(0);
        assertThat(s[1]).isBetween(0, s[0]);
      }
      reservations.put(id, d.reservation());
    }
    for (String sku : List.of("A", "B")) {
      int held = reservations.values().stream().filter(r -> r.status() == ReservationStatus.HELD)
          .flatMap(r -> r.lines().stream()).filter(l -> l.sku().equals(sku)).mapToInt(StockLine::quantity).sum();
      assertThat(stock.get(sku)[1]).isEqualTo(held);
    }
  }

  static Map<String, Integer> available(Map<String, int[]> stock) {
    Map<String, Integer> out = new HashMap<>();
    stock.forEach((k, v) -> out.put(k, v[0] - v[1]));
    return out;
  }
}
