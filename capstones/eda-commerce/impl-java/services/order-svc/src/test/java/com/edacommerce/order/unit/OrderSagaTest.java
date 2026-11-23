package com.edacommerce.order.unit;

import static com.edacommerce.order.domain.OrderSagaState.*;
import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.CancellationReason;
import com.edacommerce.order.domain.Compensation;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSaga;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaTrigger;
import com.edacommerce.order.domain.SagaTimeouts;
import java.time.Duration;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * Every row of architecture §5.1/§5.2, plus late, duplicate and out-of-order replies per waiting
 * state.
 */
class OrderSagaTest {

  @Test
  void startEmitsOrderPlacedAndReservesStock() {
    SagaRun r = SagaRun.started();
    assertThat(r.state).isEqualTo(RESERVING_STOCK);
    assertThat(r.last.events()).containsExactly(new OrderEvent.Placed(1));
    assertThat(r.last.commands())
        .containsExactly(new OrderSagaCommand.ReserveStock(r.data.reservationId, 900));
    assertThat(r.deadline).isEqualTo(SagaRun.T0.plusSeconds(30));
  }

  @Nested
  class ReservingStock {
    @Test
    void stockReservedAuthorisesPaymentWithANewPaymentId() {
      SagaRun r = SagaRun.started();
      r.on(r.reserved());
      assertThat(r.state).isEqualTo(AUTHORIZING_PAYMENT);
      assertThat(r.data.paymentId).isNotNull();
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.AuthorizePayment(r.data.paymentId));
      assertThat(r.deadline).isEqualTo(r.now.plusSeconds(180));
    }

    @Test
    void rejectionCancelsOutOfStock() {
      SagaRun r = SagaRun.started();
      r.on(new OrderSagaTrigger.StockReservationRejected(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.events())
          .containsExactly(
              new OrderEvent.Cancelled(2, CancellationReason.OUT_OF_STOCK, null, false));
      assertThat(r.last.decisionReached()).isTrue();
    }

    @Test
    void deadlineResendsTheSameReservationTwiceThenCancelsWithARelease() {
      SagaRun r = SagaRun.started();
      String id = r.data.reservationId;
      r.deadlinePasses();
      assertThat(r.last.commands()).containsExactly(new OrderSagaCommand.ReserveStock(id, 900));
      assertThat(r.last.timeout()).isTrue();
      r.deadlinePasses();
      assertThat(r.attempts).isEqualTo(2);
      r.deadlinePasses();
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.data.outstanding).containsExactly(Compensation.RELEASE_RESERVATION);
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.ReleaseReservation(id, "SAGA_TIMEOUT"));
    }

    @Test
    void repliesForAnotherReservationOrDuplicatesAreIgnored() {
      SagaRun r = SagaRun.started();
      assertThat(r.on(new OrderSagaTrigger.StockReserved("other")).ignored()).isTrue();
      r.on(r.reserved());
      assertThat(r.on(r.reserved()).ignored()).isTrue();
    }

    @Test
    void aDeadlineThatIsNotDueYetIsIgnored() {
      SagaRun r = SagaRun.started();
      assertThat(r.on(new OrderSagaTrigger.Deadline()).ignored()).isTrue();
    }

    @Test
    void lateStockReservedWhileCancellingIsCoveredByTheRelease() {
      SagaRun r = SagaRun.started();
      r.deadlinePasses();
      r.deadlinePasses();
      r.deadlinePasses();
      assertThat(r.on(r.reserved()).ignored()).isTrue();
      r.on(new OrderSagaTrigger.ReservationReleased(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.events())
          .containsExactly(
              new OrderEvent.Cancelled(2, CancellationReason.SAGA_TIMEOUT, null, false));
    }
  }

  @Nested
  class AuthorizingPayment {
    @Test
    void authorisedCommitsTheReservation() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.on(r.authorized());
      assertThat(r.state).isEqualTo(COMMITTING_STOCK);
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.CommitReservation(r.data.reservationId));
    }

    @Test
    void declineReleasesTheReservationThenCancels() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.on(new OrderSagaTrigger.PaymentDeclined(r.data.paymentId, "CARD_DECLINED"));
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.last.commands())
          .containsExactly(
              new OrderSagaCommand.ReleaseReservation(r.data.reservationId, "PAYMENT_DECLINED"));
      r.on(new OrderSagaTrigger.ReservationReleased(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.events())
          .containsExactly(
              new OrderEvent.Cancelled(
                  2, CancellationReason.PAYMENT_DECLINED, "CARD_DECLINED", false));
    }

    @Test
    void deadlineResendsOnceThenVoidsAndReleases() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.deadlinePasses();
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.AuthorizePayment(r.data.paymentId));
      r.deadlinePasses();
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.data.outstanding)
          .containsExactlyInAnyOrder(Compensation.VOID_PAYMENT, Compensation.RELEASE_RESERVATION);
    }

    @Test
    void reservationExpiredDuringASlowPaymentIsRecordedThenTheAuthorisationIsVoided() {
      // Architecture §5.7.
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.on(new OrderSagaTrigger.ReservationExpired(r.data.reservationId));
      assertThat(r.state).isEqualTo(AUTHORIZING_PAYMENT);
      assertThat(r.data.reservationExpired).isTrue();
      r.on(r.authorized());
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.last.commands())
          .containsExactly(
              new OrderSagaCommand.VoidPayment(r.data.paymentId, "RESERVATION_EXPIRED"));
      r.on(new OrderSagaTrigger.PaymentVoided(r.data.paymentId));
      assertThat(r.last.events())
          .containsExactly(
              new OrderEvent.Cancelled(2, CancellationReason.RESERVATION_EXPIRED, null, true));
    }

    @Test
    void lateAuthorisationAfterATimeoutCancellationIsVoided() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.deadlinePasses();
      r.deadlinePasses();
      r.on(new OrderSagaTrigger.PaymentDeclined(r.data.paymentId, "PSP_TIMEOUT"));
      r.on(new OrderSagaTrigger.ReservationReleased(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      r.on(r.authorized());
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.VoidPayment(r.data.paymentId, "order cancelled"));
    }
  }

  @Nested
  class CommittingStock {
    @Test
    void committedConfirmsAndRequestsFulfilment() {
      SagaRun r = SagaRun.started().to(COMMITTING_STOCK);
      r.on(r.committed());
      assertThat(r.state).isEqualTo(AWAITING_FULFILMENT_ACK);
      assertThat(r.last.events()).containsExactly(new OrderEvent.Confirmed(2));
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.RequestFulfilment(r.data.fulfilmentId, 1));
      assertThat(r.last.decisionReached()).isTrue();
    }

    @Test
    void expiredReservationVoidsThePayment() {
      SagaRun r = SagaRun.started().to(COMMITTING_STOCK);
      r.on(new OrderSagaTrigger.ReservationExpired(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.data.outstanding).containsExactly(Compensation.VOID_PAYMENT);
    }

    @Test
    void deadlineResendsTheCommit() {
      SagaRun r = SagaRun.started().to(COMMITTING_STOCK);
      r.deadlinePasses();
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.CommitReservation(r.data.reservationId));
      assertThat(r.state).isEqualTo(COMMITTING_STOCK);
    }
  }

  @Nested
  class AwaitingFulfilmentAck {
    @Test
    void acceptanceMovesToFulfilling() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      r.on(r.accepted());
      assertThat(r.state).isEqualTo(FULFILLING);
      assertThat(r.deadline).isEqualTo(r.now.plus(Duration.ofHours(24)));
    }

    @Test
    void deadlineResendsWithTheNextAttemptThreeTimesThenNeedsAttention() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      String f = r.data.fulfilmentId;
      for (int attempt = 2; attempt <= 4; attempt++) {
        r.deadlinePasses();
        assertThat(r.last.commands())
            .containsExactly(new OrderSagaCommand.RequestFulfilment(f, attempt));
      }
      r.deadlinePasses();
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
      assertThat(r.last.events()).singleElement().isInstanceOf(OrderEvent.RequiresAttention.class);
      assertThat(r.last.attention()).isTrue();
    }

    @Test
    void operatorRetryResendsAndALateAcceptanceRecovers() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      for (int i = 0; i < 4; i++) {
        r.deadlinePasses();
      }
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
      r.on(new OrderSagaTrigger.OperatorRetry());
      assertThat(r.state).isEqualTo(AWAITING_FULFILMENT_ACK);
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.RequestFulfilment(r.data.fulfilmentId, 5));
      r.on(r.accepted());
      assertThat(r.state).isEqualTo(FULFILLING);
    }

    @Test
    void fulfilmentFailureCompensatesPaymentAndStock() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      r.on(new OrderSagaTrigger.FulfilmentFailed(r.data.fulfilmentId, "STOCK_DAMAGED"));
      assertThat(r.state).isEqualTo(CANCELLING);
      assertThat(r.data.outstanding)
          .containsExactlyInAnyOrder(Compensation.VOID_PAYMENT, Compensation.RELEASE_RESERVATION);
    }

    @Test
    void packedBeforeAcceptedIsRecordedAndApplied() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      r.on(r.packed());
      assertThat(r.state).isEqualTo(AWAITING_FULFILMENT_ACK);
      assertThat(r.data.pending).hasSize(1);
      r.on(r.accepted());
      assertThat(r.state).isEqualTo(PACKED);
      assertThat(r.data.pending).isEmpty();
    }
  }

  @Nested
  class FulfillingAndPacked {
    @Test
    void packedThenDispatchedCapturesPastThePivot() {
      SagaRun r = SagaRun.started().to(FULFILLING);
      r.on(r.packed());
      assertThat(r.state).isEqualTo(PACKED);
      r.on(r.dispatched());
      assertThat(r.state).isEqualTo(CAPTURING);
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.CapturePayment(r.data.paymentId));
      assertThat(r.data.invoiceId).isNotNull();
    }

    @Test
    void failureWhilePackedCompensates() {
      SagaRun r = SagaRun.started().to(PACKED);
      r.on(new OrderSagaTrigger.FulfilmentFailed(r.data.fulfilmentId, "STOCK_NOT_FOUND"));
      assertThat(r.state).isEqualTo(CANCELLING);
      r.on(new OrderSagaTrigger.PaymentVoided(r.data.paymentId));
      r.on(new OrderSagaTrigger.ReservationReleased(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.decisionReached()).isFalse();
    }

    @Test
    void noDispatchWithin24HoursNeedsAttention() {
      SagaRun r = SagaRun.started().to(PACKED);
      r.deadlinePasses();
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
    }

    @Test
    void dispatchDeadlineIsCappedTwoDaysBeforeTheAuthorisationExpires() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.on(
          new OrderSagaTrigger.PaymentAuthorized(
              r.data.paymentId, r.now.plus(Duration.ofHours(54))));
      r.on(r.committed());
      r.on(r.accepted());
      assertThat(r.deadline).isEqualTo(r.now.plus(Duration.ofHours(6)));
    }
  }

  @Nested
  class Capturing {
    @Test
    void capturedWithShipmentDetailsShipsAndIssuesTheInvoice() {
      SagaRun r = SagaRun.started().to(CAPTURING);
      r.on(r.captured());
      assertThat(r.state).isEqualTo(SHIPPED);
      assertThat(r.last.events()).hasSize(2).first().isInstanceOf(OrderEvent.Shipped.class);
      assertThat(r.last.events().get(1))
          .isEqualTo(new OrderEvent.InvoiceToIssue(4, r.data.invoiceId));
    }

    @Test
    void capturedBeforeShipmentCreatedWaitsForIt() {
      SagaRun r = SagaRun.started().to(PACKED);
      r.on(r.dispatched());
      r.on(r.captured());
      assertThat(r.state).isEqualTo(CAPTURING);
      r.on(r.shipmentCreated());
      assertThat(r.state).isEqualTo(SHIPPED);
    }

    @Test
    void retryableCaptureFailureResendsAfterBackoffAndNonRetryableNeedsAttention() {
      SagaRun r = SagaRun.started().to(CAPTURING);
      r.on(new OrderSagaTrigger.PaymentCaptureFailed(r.data.paymentId, "PSP_ERROR", true));
      assertThat(r.state).isEqualTo(CAPTURING);
      assertThat(r.deadline).isEqualTo(r.now.plus(SagaTimeouts.CAPTURE_RETRY_BACKOFF));
      r.deadlinePasses();
      assertThat(r.last.commands())
          .containsExactly(new OrderSagaCommand.CapturePayment(r.data.paymentId));
      r.on(
          new OrderSagaTrigger.PaymentCaptureFailed(
              r.data.paymentId, "AUTHORIZATION_EXPIRED", false));
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
      assertThat(r.last.commands()).isEmpty(); // no compensation past the pivot
      r.on(new OrderSagaTrigger.OperatorRetry());
      assertThat(r.state).isEqualTo(CAPTURING);
    }

    @Test
    void deliveredBeforeCapturedIsAppliedAfterShipping() {
      SagaRun r = SagaRun.started().to(CAPTURING);
      r.on(r.delivered());
      assertThat(r.state).isEqualTo(CAPTURING);
      r.on(r.captured());
      assertThat(r.state).isEqualTo(DELIVERED);
      assertThat(r.allEvents).last().isInstanceOf(OrderEvent.Delivered.class);
    }

    @Test
    void lateDispatchOrDuplicateCaptureIsIgnored() {
      SagaRun r = SagaRun.started().to(CAPTURING);
      assertThat(r.on(r.dispatched()).ignored()).isTrue();
      r.on(r.captured());
      assertThat(r.on(r.captured()).ignored()).isTrue();
    }
  }

  @Nested
  class Shipped {
    @Test
    void deliveredEndsTheSagaWithAReturnWindow() {
      SagaRun r = SagaRun.started().to(SHIPPED);
      r.on(r.delivered());
      assertThat(r.state).isEqualTo(DELIVERED);
      OrderEvent.Delivered d = (OrderEvent.Delivered) r.last.events().get(0);
      assertThat(d.returnWindowEndsAt()).isEqualTo(d.deliveredAt().plus(Duration.ofDays(30)));
      assertThat(r.last.terminal()).isTrue();
      assertThat(r.on(r.delivered()).ignored()).isTrue();
    }

    @Test
    void lostParcelNeedsAttentionOtherExceptionsAreIgnored() {
      SagaRun r = SagaRun.started().to(SHIPPED);
      assertThat(
              r.on(new OrderSagaTrigger.ShipmentException("ship-1", true, false, "DELAYED"))
                  .ignored())
          .isTrue();
      r.on(new OrderSagaTrigger.ShipmentException("ship-1", true, true, "LOST"));
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
    }

    @Test
    void returnShipmentsAndUnknownDirectionsAreNotForThisSaga() {
      SagaRun r = SagaRun.started().to(SHIPPED);
      assertThat(r.on(new OrderSagaTrigger.ShipmentDelivered("ret", false, r.now)).ignored())
          .isTrue();
    }

    @Test
    void thirtyDaysWithoutDeliveryNeedsAttention() {
      SagaRun r = SagaRun.started().to(SHIPPED);
      r.deadlinePasses();
      assertThat(r.state).isEqualTo(NEEDS_ATTENTION);
    }
  }

  @Nested
  class Cancelling {
    @Test
    void deadlineResendsOutstandingCompensationsWithBackoff() {
      SagaRun r = SagaRun.started().to(AUTHORIZING_PAYMENT);
      r.on(new OrderSagaTrigger.PaymentDeclined(r.data.paymentId, "CARD_DECLINED"));
      r.deadlinePasses();
      assertThat(r.last.commands())
          .containsExactly(
              new OrderSagaCommand.ReleaseReservation(r.data.reservationId, "PAYMENT_DECLINED"));
      assertThat(r.deadline).isEqualTo(r.now.plus(Duration.ofSeconds(120)));
      r.deadlinePasses();
      assertThat(r.deadline).isEqualTo(r.now.plus(Duration.ofSeconds(240)));
    }

    @Test
    void duplicateCompensationRepliesAreIgnored() {
      SagaRun r = SagaRun.started().to(AWAITING_FULFILMENT_ACK);
      r.on(new OrderSagaTrigger.FulfilmentFailed(r.data.fulfilmentId, "X"));
      r.on(new OrderSagaTrigger.PaymentVoided(r.data.paymentId));
      assertThat(r.on(new OrderSagaTrigger.PaymentVoided(r.data.paymentId)).ignored()).isTrue();
      r.on(new OrderSagaTrigger.ReservationReleased(r.data.reservationId));
      assertThat(r.state).isEqualTo(CANCELLED);
      assertThat(r.last.events())
          .containsExactly(
              new OrderEvent.Cancelled(3, CancellationReason.FULFILMENT_FAILED, "X", true));
    }
  }

  @Test
  void terminalStatesIgnoreEverything() {
    SagaRun r = SagaRun.started().to(DELIVERED);
    assertThat(r.on(r.captured()).ignored()).isTrue();
    assertThat(r.on(new OrderSagaTrigger.OperatorRetry()).ignored()).isTrue();
    assertThat(r.on(new OrderSagaTrigger.Deadline()).ignored()).isTrue();
  }

  @Test
  void eventVersionsStrictlyIncrease() {
    SagaRun r = SagaRun.started().to(DELIVERED);
    assertThat(r.allEvents).extracting(OrderEvent::version).containsExactly(1L, 2L, 3L, 4L, 5L);
    assertThat(OrderSaga.start("o", Money.of(1, "EUR"), r.ctx()).events()).hasSize(1);
  }
}
