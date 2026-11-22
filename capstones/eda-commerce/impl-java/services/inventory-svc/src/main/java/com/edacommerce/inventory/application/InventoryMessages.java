package com.edacommerce.inventory.application;

import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.inventory.ItemsRestocked;
import com.edacommerce.inventory.ReservationCommitted;
import com.edacommerce.inventory.ReservationExpired;
import com.edacommerce.inventory.ReservationReleased;
import com.edacommerce.inventory.StockLevelChanged;
import com.edacommerce.inventory.StockReservationRejected;
import com.edacommerce.inventory.StockReserved;
import com.edacommerce.inventory.domain.Reply;
import com.edacommerce.inventory.domain.Reservation;
import com.edacommerce.inventory.domain.Restock;
import com.edacommerce.inventory.domain.StockLevel;
import com.edacommerce.inventory.domain.StockLine;
import java.time.Instant;
import java.util.List;
import org.apache.avro.specific.SpecificRecord;

/** Domain replies -> contract messages (topics, keys and aggregates of contracts/topics.yaml). */
public final class InventoryMessages {
  private InventoryMessages() {}

  public static final String EVENTS = "inventory.events.v1";
  public static final String STOCK_LEVEL = "inventory.stock-level.v1";

  public static OutgoingMessage reply(Reservation r, Reply reply) {
    SpecificRecord record =
        switch (reply) {
          case Reply.Reserved x ->
              StockReserved.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(r.orderId())
                  .setReservationId(r.reservationId())
                  .setLines(lines(x.lines()))
                  .setExpiresAt(x.expiresAt())
                  .build();
          case Reply.Rejected x ->
              StockReservationRejected.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(r.orderId())
                  .setReservationId(r.reservationId())
                  .setShortages(
                      x.shortages().stream()
                          .map(s -> new com.edacommerce.inventory.Shortage(s.sku(), s.requested(), s.available()))
                          .toList())
                  .build();
          case Reply.Committed x ->
              ReservationCommitted.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(r.orderId())
                  .setReservationId(r.reservationId())
                  .setCommittedAt(x.committedAt())
                  .build();
          case Reply.Released x ->
              ReservationReleased.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(r.orderId())
                  .setReservationId(r.reservationId())
                  .setReason(x.reason())
                  .setReleasedAt(x.releasedAt())
                  .build();
          case Reply.Expired x ->
              ReservationExpired.newBuilder()
                  .setEnvelope(Envelopes.placeholder())
                  .setOrderId(r.orderId())
                  .setReservationId(r.reservationId())
                  .setExpiredAt(x.expiredAt())
                  .build();
        };
    return OutgoingMessage.of(EVENTS, r.orderId(), record, "Reservation", r.reservationId(), r.version());
  }

  public static OutgoingMessage restocked(Restock r) {
    ItemsRestocked e =
        ItemsRestocked.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setOrderId(r.orderId())
            .setReturnId(r.returnId())
            .setRestockId(r.restockId())
            .setLines(lines(r.lines()))
            .setRestockedAt(r.restockedAt())
            .build();
    return OutgoingMessage.of(EVENTS, r.orderId(), e, "Restock", r.restockId(), 1);
  }

  public static OutgoingMessage stockLevel(StockLevel level, Instant asOf) {
    StockLevelChanged e =
        StockLevelChanged.newBuilder()
            .setEnvelope(Envelopes.placeholder())
            .setSku(level.sku())
            .setOnHand(level.onHand())
            .setReserved(level.reserved())
            .setAvailable(level.available())
            .setAsOf(asOf)
            .build();
    return OutgoingMessage.of(STOCK_LEVEL, level.sku(), e, "StockLevel", level.sku(), level.version());
  }

  static List<com.edacommerce.common.StockLine> lines(List<StockLine> lines) {
    return lines.stream().map(l -> new com.edacommerce.common.StockLine(l.sku(), l.quantity())).toList();
  }
}
