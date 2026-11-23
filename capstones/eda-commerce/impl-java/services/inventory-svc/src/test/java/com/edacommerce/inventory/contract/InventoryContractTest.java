package com.edacommerce.inventory.contract;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.inventory.CommitReservation;
import com.edacommerce.inventory.ReleaseReservation;
import com.edacommerce.inventory.ReserveStock;
import com.edacommerce.inventory.RestockItems;
import com.edacommerce.inventory.application.InventoryMessages;
import com.edacommerce.inventory.domain.Reply;
import com.edacommerce.inventory.domain.Reservation;
import com.edacommerce.inventory.domain.ReservationStatus;
import com.edacommerce.inventory.domain.Restock;
import com.edacommerce.inventory.domain.Shortage;
import com.edacommerce.inventory.domain.StockLevel;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Instant;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Layer 2: golden messages this service consumes decode; everything it produces validates. */
class InventoryContractTest {
  static final Instant T = Instant.parse("2026-11-18T09:00:00Z");

  @Test
  void consumedCommandsDecodeFromTheirGoldenBytes() {
    assertThat(GoldenFixtures.assertSpecificRoundTrip(ReserveStock.class).getTtlSeconds())
        .isEqualTo(900);
    GoldenFixtures.assertSpecificRoundTrip(CommitReservation.class);
    GoldenFixtures.assertSpecificRoundTrip(ReleaseReservation.class);
    GoldenFixtures.assertSpecificRoundTrip(RestockItems.class);
  }

  @Test
  void everyProducedMessageValidatesAgainstTheBundledSchema() {
    Reservation r =
        new Reservation(
            "r1",
            "o1",
            ReservationStatus.HELD,
            List.of(new StockLine("SKU-1", 1)),
            T,
            List.of(),
            null,
            T,
            1);
    List<Reply> replies =
        List.of(
            new Reply.Reserved(r.lines(), T),
            new Reply.Rejected(List.of(new Shortage("SKU-1", 2, 1))),
            new Reply.Committed(T),
            new Reply.Released("x", T),
            new Reply.Expired(T));
    for (Reply reply : replies) {
      OutgoingMessage m = InventoryMessages.reply(r, reply);
      assertThat(m.topic()).isEqualTo("inventory.events.v1");
      assertThat(m.key()).isEqualTo("o1");
      GoldenFixtures.assertValidAgainstBundled(m.record());
    }
    OutgoingMessage level = InventoryMessages.stockLevel(new StockLevel("SKU-1", 5, 2, 7), T);
    assertThat(level.topic()).isEqualTo("inventory.stock-level.v1");
    assertThat(level.key()).isEqualTo("SKU-1");
    assertThat(level.aggregateVersion()).isEqualTo(7);
    GoldenFixtures.assertValidAgainstBundled(level.record());
    GoldenFixtures.assertValidAgainstBundled(
        InventoryMessages.restocked(
                new Restock("rs", "o1", "ret", List.of(new StockLine("SKU-1", 1)), T))
            .record());
  }
}
