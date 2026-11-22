package com.edacommerce.inventory.unit;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.inventory.domain.InventoryException;
import com.edacommerce.inventory.domain.Reply;
import com.edacommerce.inventory.domain.Reservation;
import com.edacommerce.inventory.domain.ReservationStatus;
import com.edacommerce.inventory.domain.Restock;
import com.edacommerce.inventory.domain.Shortage;
import com.edacommerce.inventory.domain.StockEffect;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class ReservationTest {
  static final Instant T0 = Instant.parse("2026-11-18T09:00:00Z");
  static final Duration TTL = Duration.ofMinutes(15);

  static Reservation held() {
    return Reservation.reserve(
            Optional.empty(),
            "r1",
            "o1",
            List.of(new StockLine("SKU-1", 2), new StockLine("SKU-2", 1)),
            TTL,
            Map.of("SKU-1", 5, "SKU-2", 1),
            false,
            T0)
        .reservation();
  }

  @Test
  void reservesAllLinesOrNone() {
    Reservation.Decision ok =
        Reservation.reserve(
            Optional.empty(),
            "r1",
            "o1",
            List.of(
                new StockLine("SKU-2", 1), new StockLine("SKU-1", 1), new StockLine("SKU-1", 1)),
            TTL,
            Map.of("SKU-1", 2, "SKU-2", 1),
            false,
            T0);
    assertThat(ok.reservation().status()).isEqualTo(ReservationStatus.HELD);
    assertThat(ok.reservation().lines())
        .containsExactly(new StockLine("SKU-1", 2), new StockLine("SKU-2", 1));
    assertThat(ok.reply()).isEqualTo(new Reply.Reserved(ok.reservation().lines(), T0.plus(TTL)));
    assertThat(ok.effects())
        .containsExactly(new StockEffect.Reserve("SKU-1", 2), new StockEffect.Reserve("SKU-2", 1));

    Reservation.Decision short1 =
        Reservation.reserve(
            Optional.empty(),
            "r2",
            "o2",
            List.of(new StockLine("SKU-1", 3), new StockLine("SKU-2", 1)),
            TTL,
            Map.of("SKU-1", 2, "SKU-2", 1),
            false,
            T0);
    assertThat(short1.reservation().status()).isEqualTo(ReservationStatus.REJECTED);
    assertThat(short1.effects()).isEmpty();
    assertThat(short1.reply()).isEqualTo(new Reply.Rejected(List.of(new Shortage("SKU-1", 3, 2))));
  }

  @Test
  void unknownSkuIsAShortageOfZero() {
    Reservation.Decision d =
        Reservation.reserve(
            Optional.empty(),
            "r",
            "o",
            List.of(new StockLine("NOPE", 1)),
            TTL,
            Map.of(),
            false,
            T0);
    assertThat(d.reply()).isEqualTo(new Reply.Rejected(List.of(new Shortage("NOPE", 1, 0))));
  }

  @Test
  void aResendReplaysTheOriginalReplyWithoutTouchingStock() {
    Reservation r = held();
    Reservation.Decision again =
        Reservation.reserve(
            Optional.of(r),
            "r1",
            "o1",
            List.of(new StockLine("SKU-1", 99)),
            TTL,
            Map.of(),
            false,
            T0.plusSeconds(5));
    assertThat(again.changed()).isFalse();
    assertThat(again.effects()).isEmpty();
    assertThat(again.reply()).isInstanceOf(Reply.Reserved.class);
  }

  @Test
  void anExpiredCommandIsRejected() {
    Reservation.Decision d =
        Reservation.reserve(
            Optional.empty(),
            "r",
            "o",
            List.of(new StockLine("SKU-1", 1)),
            TTL,
            Map.of("SKU-1", 9),
            true,
            T0);
    assertThat(d.reservation().status()).isEqualTo(ReservationStatus.REJECTED);
  }

  @Test
  void commitBeforeTtlAllocatesAndCommitAfterTtlExpires() {
    Reservation.Decision c = held().commit(T0.plusSeconds(60));
    assertThat(c.reservation().status()).isEqualTo(ReservationStatus.COMMITTED);
    assertThat(c.effects())
        .containsExactly(
            new StockEffect.Allocate("SKU-1", 2), new StockEffect.Allocate("SKU-2", 1));
    assertThat(c.reservation().commit(T0.plusSeconds(61)).changed()).isFalse();

    Reservation.Decision late = held().commit(T0.plus(TTL));
    assertThat(late.reservation().status()).isEqualTo(ReservationStatus.EXPIRED);
    assertThat(late.reply()).isEqualTo(new Reply.Expired(T0.plus(TTL)));
    assertThat(late.effects())
        .containsExactly(
            new StockEffect.Unreserve("SKU-1", 2), new StockEffect.Unreserve("SKU-2", 1));
  }

  @Test
  void commitAfterTheSweeperExpiredItAnswersExpired() {
    Reservation expired = held().expire(T0.plus(TTL)).reservation();
    Reservation.Decision d = expired.commit(T0.plus(TTL).plusSeconds(1));
    assertThat(d.reply()).isInstanceOf(Reply.Expired.class);
    assertThat(d.effects()).isEmpty();
  }

  @Test
  void releaseReturnsHeldOrAllocatedStockOnceAndIsIdempotent() {
    Reservation.Decision fromHeld = held().release("payment declined", T0.plusSeconds(1));
    assertThat(fromHeld.effects())
        .containsExactly(
            new StockEffect.Unreserve("SKU-1", 2), new StockEffect.Unreserve("SKU-2", 1));
    Reservation.Decision twice = fromHeld.reservation().release("again", T0.plusSeconds(2));
    assertThat(twice.effects()).isEmpty();
    assertThat(twice.reply()).isEqualTo(new Reply.Released("payment declined", T0.plusSeconds(1)));

    Reservation committed = held().commit(T0.plusSeconds(1)).reservation();
    assertThat(committed.release("fulfilment failed", T0.plusSeconds(2)).effects())
        .containsExactly(new StockEffect.Return("SKU-1", 2), new StockEffect.Return("SKU-2", 1));
  }

  @Test
  void releasingAnExpiredOrUnknownReservationConfirmsWithoutStockChanges() {
    Reservation expired = held().expire(T0.plus(TTL)).reservation();
    assertThat(expired.release("cancel", T0.plus(TTL)).effects()).isEmpty();
    assertThat(expired.release("cancel", T0.plus(TTL)).reply()).isInstanceOf(Reply.Released.class);

    Reservation.Decision tombstone = Reservation.releaseUnknown("r9", "o9", "timeout", T0);
    assertThat(tombstone.reservation().status()).isEqualTo(ReservationStatus.RELEASED);
    // A ReserveStock that arrives after its release is a no-op.
    Reservation.Decision late =
        Reservation.reserve(
            Optional.of(tombstone.reservation()),
            "r9",
            "o9",
            List.of(new StockLine("SKU-1", 1)),
            TTL,
            Map.of("SKU-1", 5),
            false,
            T0);
    assertThat(late.effects()).isEmpty();
    assertThat(late.reply()).isInstanceOf(Reply.Released.class);
  }

  @Test
  void onlyHeldReservationsExpire() {
    Reservation committed = held().commit(T0.plusSeconds(1)).reservation();
    assertThat(committed.expire(T0.plus(TTL)).changed()).isFalse();
  }

  @Test
  void restockIsIdempotentOnRestockId() {
    Restock.Decision first =
        Restock.apply(
            Optional.empty(), "rs1", "o1", "ret1", List.of(new StockLine("SKU-1", 1)), T0);
    assertThat(first.effects()).containsExactly(new StockEffect.Return("SKU-1", 1));
    assertThat(
            Restock.apply(
                    Optional.of(first.restock()),
                    "rs1",
                    "o1",
                    "ret1",
                    List.of(new StockLine("SKU-1", 1)),
                    T0)
                .effects())
        .isEmpty();
  }

  @Test
  void invalidLinesAreRejected() {
    assertThatThrownBy(() -> new StockLine("SKU-1", 0)).isInstanceOf(InventoryException.class);
  }
}
