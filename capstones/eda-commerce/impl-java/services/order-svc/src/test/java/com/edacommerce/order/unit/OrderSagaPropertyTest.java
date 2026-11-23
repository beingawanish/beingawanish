package com.edacommerce.order.unit;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.Compensation;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaState;
import com.edacommerce.order.domain.OrderSagaTrigger;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import net.jqwik.api.ForAll;
import net.jqwik.api.Property;
import net.jqwik.api.constraints.IntRange;
import net.jqwik.api.constraints.Size;

/**
 * Checklist: random interleavings of replies (including duplicates, late and out-of-order ones, and
 * deadlines) always end in a terminal or attention state, with compensations consistent with what
 * was done: an authorisation that was not captured is voided, a held reservation is released,
 * nothing is both captured and cancelled.
 */
class OrderSagaPropertyTest {
  static final int KINDS = 20;

  @Property(tries = 1000)
  void everyInterleavingSettlesConsistently(
      @ForAll @Size(max = 60) List<@IntRange(min = 0, max = KINDS - 1) Integer> script) {
    SagaRun r = SagaRun.started();
    for (int k : script) {
      if (r.state.isTerminal()) {
        break;
      }
      r.on(trigger(r, k));
    }
    // Drain: participants confirm compensations and steps that are resent forever; time passes
    // otherwise.
    for (int i = 0; i < 60 && !settled(r.state); i++) {
      if (r.state == OrderSagaState.CANCELLING && !r.data.outstanding.isEmpty()) {
        Compensation c = r.data.outstanding.iterator().next();
        r.on(
            switch (c) {
              case RELEASE_RESERVATION ->
                  new OrderSagaTrigger.ReservationReleased(r.data.reservationId);
              case VOID_PAYMENT -> new OrderSagaTrigger.PaymentVoided(r.data.paymentId);
              case CANCEL_FULFILMENT ->
                  new OrderSagaTrigger.FulfilmentCancelled(r.data.fulfilmentId);
            });
      } else if (r.state == OrderSagaState.COMMITTING_STOCK && r.attempts > 2) {
        // Steps the table resends forever are answered eventually by a healthy participant.
        r.on(new OrderSagaTrigger.ReservationCommitted(r.data.reservationId));
      } else if (r.state == OrderSagaState.CAPTURING && r.attempts > 2) {
        r.on(
            r.data.captured
                ? new OrderSagaTrigger.ShipmentCreated("s1", true, "c", "t")
                : new OrderSagaTrigger.PaymentCaptured(r.data.paymentId, Money.of(12999, "EUR")));
      } else {
        r.deadlinePasses();
      }
    }
    assertThat(r.state)
        .isIn(OrderSagaState.DELIVERED, OrderSagaState.CANCELLED, OrderSagaState.NEEDS_ATTENTION);

    boolean captureSent =
        r.allCommands.stream().anyMatch(c -> c instanceof OrderSagaCommand.CapturePayment);
    boolean voidSent =
        r.allCommands.stream().anyMatch(c -> c instanceof OrderSagaCommand.VoidPayment);
    boolean cancelled = r.allEvents.stream().anyMatch(e -> e instanceof OrderEvent.Cancelled);
    assertThat(captureSent && cancelled).as("never both captured and cancelled").isFalse();
    if (r.state == OrderSagaState.DELIVERED) {
      assertThat(voidSent).isFalse();
    }
    if (cancelled && r.data.paymentId != null && r.data.authorizationExpiresAt != null) {
      assertThat(voidSent).as("an authorised payment of a cancelled order is voided").isTrue();
    }
    if (cancelled && r.data.paymentId != null) {
      boolean reservedOk =
          r.allCommands.stream().anyMatch(c -> c instanceof OrderSagaCommand.AuthorizePayment);
      boolean released =
          r.allCommands.stream().anyMatch(c -> c instanceof OrderSagaCommand.ReleaseReservation);
      if (reservedOk && !r.data.reservationExpired) {
        assertThat(released).as("a held reservation of a cancelled order is released").isTrue();
      }
    }
    assertThat(r.allEvents.stream().map(OrderEvent::version).toList())
        .isSorted()
        .doesNotHaveDuplicates();
  }

  static boolean settled(OrderSagaState s) {
    return Set.of(
            OrderSagaState.DELIVERED, OrderSagaState.CANCELLED, OrderSagaState.NEEDS_ATTENTION)
        .contains(s);
  }

  static OrderSagaTrigger trigger(SagaRun r, int k) {
    String res = r.data.reservationId;
    String pay = r.data.paymentId == null ? "none" : r.data.paymentId;
    String ful = r.data.fulfilmentId == null ? "none" : r.data.fulfilmentId;
    return switch (k) {
      case 0, 1 -> new OrderSagaTrigger.StockReserved(res);
      case 2 -> new OrderSagaTrigger.StockReservationRejected(res);
      case 3 -> new OrderSagaTrigger.PaymentAuthorized(pay, r.now.plus(Duration.ofDays(7)));
      case 4 -> new OrderSagaTrigger.PaymentDeclined(pay, "CARD_DECLINED");
      case 5 -> new OrderSagaTrigger.ReservationCommitted(res);
      case 6 -> new OrderSagaTrigger.ReservationExpired(res);
      case 7 -> new OrderSagaTrigger.FulfilmentAccepted(ful);
      case 8 -> new OrderSagaTrigger.OrderPacked(ful);
      case 9 -> new OrderSagaTrigger.OrderDispatched(ful, "s1");
      case 10 -> new OrderSagaTrigger.FulfilmentFailed(ful, "STOCK_DAMAGED");
      case 11 -> new OrderSagaTrigger.ShipmentCreated("s1", true, "c", "t");
      case 12 -> new OrderSagaTrigger.PaymentCaptured(pay, Money.of(12999, "EUR"));
      case 13 -> new OrderSagaTrigger.PaymentCaptureFailed(pay, "PSP_ERROR", true);
      case 14 -> new OrderSagaTrigger.ShipmentDelivered("s1", true, r.now);
      case 15 -> new OrderSagaTrigger.ReservationReleased(res);
      case 16 -> new OrderSagaTrigger.PaymentVoided(pay);
      case 17 -> new OrderSagaTrigger.OperatorRetry();
      default -> {
        r.advance(Duration.ofMinutes(11));
        yield new OrderSagaTrigger.Deadline();
      }
    };
  }
}
