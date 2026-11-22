package com.edacommerce.order.domain;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.OrderSagaCommand.AuthorizePayment;
import com.edacommerce.order.domain.OrderSagaCommand.CancelFulfilment;
import com.edacommerce.order.domain.OrderSagaCommand.CapturePayment;
import com.edacommerce.order.domain.OrderSagaCommand.CommitReservation;
import com.edacommerce.order.domain.OrderSagaCommand.ReleaseReservation;
import com.edacommerce.order.domain.OrderSagaCommand.RequestFulfilment;
import com.edacommerce.order.domain.OrderSagaCommand.ReserveStock;
import com.edacommerce.order.domain.OrderSagaCommand.VoidPayment;
import com.edacommerce.order.domain.OrderSagaTrigger.Deadline;
import com.edacommerce.order.domain.OrderSagaTrigger.FulfilmentAccepted;
import com.edacommerce.order.domain.OrderSagaTrigger.FulfilmentCancelled;
import com.edacommerce.order.domain.OrderSagaTrigger.FulfilmentFailed;
import com.edacommerce.order.domain.OrderSagaTrigger.OperatorRetry;
import com.edacommerce.order.domain.OrderSagaTrigger.OrderDispatched;
import com.edacommerce.order.domain.OrderSagaTrigger.OrderPacked;
import com.edacommerce.order.domain.OrderSagaTrigger.PaymentAuthorized;
import com.edacommerce.order.domain.OrderSagaTrigger.PaymentCaptureFailed;
import com.edacommerce.order.domain.OrderSagaTrigger.PaymentCaptured;
import com.edacommerce.order.domain.OrderSagaTrigger.PaymentDeclined;
import com.edacommerce.order.domain.OrderSagaTrigger.PaymentVoided;
import com.edacommerce.order.domain.OrderSagaTrigger.ReservationCommitted;
import com.edacommerce.order.domain.OrderSagaTrigger.ReservationExpired;
import com.edacommerce.order.domain.OrderSagaTrigger.ReservationReleased;
import com.edacommerce.order.domain.OrderSagaTrigger.ShipmentCreated;
import com.edacommerce.order.domain.OrderSagaTrigger.ShipmentDelivered;
import com.edacommerce.order.domain.OrderSagaTrigger.ShipmentException;
import com.edacommerce.order.domain.OrderSagaTrigger.StockReservationRejected;
import com.edacommerce.order.domain.OrderSagaTrigger.StockReserved;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * The order saga as a pure function (ADR-0008): {@code (state, data, trigger, now) -> decision}. This
 * class is the executable form of the state machine in architecture §5.1 and the step table in §5.2.
 * No I/O, no clock, no framework: the application layer persists the decision in one transaction.
 */
public final class OrderSaga {
  private OrderSaga() {}

  /** Where the saga is now (the persisted row). */
  public record Snapshot(OrderSagaState state, OrderSagaData data, Instant deadlineAt, int stepAttempts) {}

  /** Inputs that are not saga state. */
  public record Context(Instant now, IdSource ids, SagaTimeouts timeouts) {}

  /** The outcome of one trigger. {@code ignored}: nothing to persist. */
  public record Decision(
      boolean ignored,
      OrderSagaState state,
      OrderSagaData data,
      List<OrderSagaCommand> commands,
      List<OrderEvent> events,
      Instant deadlineAt,
      int stepAttempts,
      boolean timeout,
      boolean decisionReached) {

    public boolean terminal() {
      return state != null && state.isTerminal();
    }

    public boolean attention() {
      return state == OrderSagaState.NEEDS_ATTENTION;
    }
  }

  /** CheckoutSubmitted: create the saga, emit OrderPlaced, send ReserveStock. */
  public static Decision start(String orderId, Money total, Context ctx) {
    OrderSagaData d = new OrderSagaData();
    d.orderId = orderId;
    d.total = total;
    d.reservationId = ctx.ids().next();
    Step s = new Step(OrderSagaState.RESERVING_STOCK, d, null, 0);
    s.event(new OrderEvent.Placed(d.nextVersion()));
    s.command(new ReserveStock(d.reservationId, SagaTimeouts.RESERVATION_TTL_SECONDS));
    s.deadline(ctx.now().plus(ctx.timeouts().stock()), 0);
    return s.decide();
  }

  /**
   * Applies {@code trigger}, then any recorded early events that the new state now expects
   * (architecture §5.3 rule 4).
   */
  public static Decision apply(Snapshot current, OrderSagaTrigger trigger, Context ctx) {
    Step s = new Step(current.state(), current.data().copy(), current.deadlineAt(), current.stepAttempts());
    Outcome first = step(s, trigger, ctx);
    if (first == Outcome.IGNORED) {
      return Step.ignored();
    }
    if (first == Outcome.DEFERRED) {
      s.data.pending.add(trigger);
      return s.decide();
    }
    boolean progress = true;
    while (progress) {
      progress = false;
      for (Iterator<OrderSagaTrigger> it = s.data.pending.iterator(); it.hasNext(); ) {
        OrderSagaTrigger p = it.next();
        Step trial = s.fork();
        Outcome o = step(trial, p, ctx);
        if (o == Outcome.APPLIED) {
          trial.data.pending.remove(p);
          s.absorb(trial);
          progress = true;
          break;
        }
        if (o == Outcome.IGNORED && !isDeferrable(p)) {
          it.remove();
        }
      }
    }
    return s.decide();
  }

  enum Outcome {
    APPLIED,
    IGNORED,
    DEFERRED
  }

  private static boolean isDeferrable(OrderSagaTrigger t) {
    return t instanceof ShipmentDelivered || t instanceof ShipmentException || t instanceof OrderPacked
        || t instanceof OrderDispatched;
  }

  @SuppressWarnings("StatementSwitchToExpressionSwitch")
  private static Outcome step(Step s, OrderSagaTrigger trigger, Context ctx) {
    OrderSagaData d = s.data;
    SagaTimeouts t = ctx.timeouts();
    Instant now = ctx.now();
    OrderSagaState st = s.state;
    switch (trigger) {
      case StockReserved r -> {
        if (!r.reservationId().equals(d.reservationId) || st != OrderSagaState.RESERVING_STOCK) {
          return Outcome.IGNORED;
        }
        d.paymentId = ctx.ids().next();
        s.to(OrderSagaState.AUTHORIZING_PAYMENT).command(new AuthorizePayment(d.paymentId)).deadline(now.plus(t.payment()), 0);
        return Outcome.APPLIED;
      }
      case StockReservationRejected r -> {
        if (!r.reservationId().equals(d.reservationId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.RESERVING_STOCK) {
          d.cancellationReason = CancellationReason.OUT_OF_STOCK;
          cancelled(s);
          return Outcome.APPLIED;
        }
        return compensationConfirmed(s, Compensation.RELEASE_RESERVATION);
      }
      case ReservationCommitted r -> {
        if (!r.reservationId().equals(d.reservationId) || st != OrderSagaState.COMMITTING_STOCK) {
          return Outcome.IGNORED;
        }
        d.confirmed = true;
        d.fulfilmentId = ctx.ids().next();
        d.fulfilmentAttempt = 1;
        s.to(OrderSagaState.AWAITING_FULFILMENT_ACK)
            .event(new OrderEvent.Confirmed(d.nextVersion()))
            .command(new RequestFulfilment(d.fulfilmentId, 1))
            .deadline(now.plus(t.fulfilmentAck()), 0);
        s.decisionReached = true;
        return Outcome.APPLIED;
      }
      case ReservationReleased r -> {
        return r.reservationId().equals(d.reservationId) ? compensationConfirmed(s, Compensation.RELEASE_RESERVATION) : Outcome.IGNORED;
      }
      case ReservationExpired r -> {
        if (!r.reservationId().equals(d.reservationId)) {
          return Outcome.IGNORED;
        }
        switch (st) {
          case RESERVING_STOCK, AUTHORIZING_PAYMENT -> {
            if (d.reservationExpired) {
              return Outcome.IGNORED;
            }
            d.reservationExpired = true; // recorded; acted on when the payment reply arrives (§5.7)
            return Outcome.APPLIED;
          }
          case COMMITTING_STOCK -> {
            d.reservationExpired = true;
            d.cancellationReason = CancellationReason.RESERVATION_EXPIRED;
            startCancelling(s, ctx, Compensation.VOID_PAYMENT);
            return Outcome.APPLIED;
          }
          default -> {
            return compensationConfirmed(s, Compensation.RELEASE_RESERVATION);
          }
        }
      }
      case PaymentAuthorized p -> {
        if (!p.paymentId().equals(d.paymentId)) {
          return Outcome.IGNORED;
        }
        d.authorizationExpiresAt = p.authorizationExpiresAt();
        switch (st) {
          case AUTHORIZING_PAYMENT -> {
            if (d.reservationExpired) {
              d.cancellationReason = CancellationReason.RESERVATION_EXPIRED;
              startCancelling(s, ctx, Compensation.VOID_PAYMENT);
            } else {
              s.to(OrderSagaState.COMMITTING_STOCK).command(new CommitReservation(d.reservationId)).deadline(now.plus(t.commit()), 0);
            }
            return Outcome.APPLIED;
          }
          case CANCELLING -> {
            // A success that arrives while cancelling is not an error: void it (§5.3 rule 3).
            if (d.outstanding.contains(Compensation.VOID_PAYMENT) || d.paymentVoided) {
              return Outcome.IGNORED;
            }
            d.outstanding.add(Compensation.VOID_PAYMENT);
            s.command(new VoidPayment(d.paymentId, "order cancelled"));
            return Outcome.APPLIED;
          }
          case CANCELLED -> {
            if (d.paymentVoided) {
              return Outcome.IGNORED;
            }
            s.command(new VoidPayment(d.paymentId, "order cancelled"));
            d.paymentVoided = true;
            return Outcome.APPLIED;
          }
          default -> {
            return Outcome.IGNORED;
          }
        }
      }
      case PaymentDeclined p -> {
        if (!p.paymentId().equals(d.paymentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.AUTHORIZING_PAYMENT) {
          d.cancellationReason = CancellationReason.PAYMENT_DECLINED;
          d.cancellationDetail = p.reason();
          if (d.reservationExpired) {
            cancelled(s);
          } else {
            startCancelling(s, ctx, Compensation.RELEASE_RESERVATION);
          }
          return Outcome.APPLIED;
        }
        // Nothing was authorised, so there is nothing to void.
        return compensationConfirmed(s, Compensation.VOID_PAYMENT);
      }
      case PaymentVoided p -> {
        if (!p.paymentId().equals(d.paymentId) || st != OrderSagaState.CANCELLING || !d.outstanding.contains(Compensation.VOID_PAYMENT)) {
          return Outcome.IGNORED;
        }
        d.paymentVoided = true;
        return compensationConfirmed(s, Compensation.VOID_PAYMENT);
      }
      case FulfilmentAccepted f -> {
        if (!f.fulfilmentId().equals(d.fulfilmentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.AWAITING_FULFILMENT_ACK || attentionFrom(s, OrderSagaState.AWAITING_FULFILMENT_ACK)) {
          s.to(OrderSagaState.FULFILLING).deadline(dispatchDeadline(d, ctx), 0);
          return Outcome.APPLIED;
        }
        return Outcome.IGNORED;
      }
      case OrderPacked f -> {
        if (!f.fulfilmentId().equals(d.fulfilmentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.FULFILLING || attentionFrom(s, OrderSagaState.AWAITING_FULFILMENT_ACK)) {
          s.to(OrderSagaState.PACKED).deadline(dispatchDeadline(d, ctx), 0);
          return Outcome.APPLIED;
        }
        return st == OrderSagaState.AWAITING_FULFILMENT_ACK ? Outcome.DEFERRED : Outcome.IGNORED;
      }
      case OrderDispatched f -> {
        if (!f.fulfilmentId().equals(d.fulfilmentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.PACKED) {
          // The pivot: from here on nothing is compensated (ADR-0015).
          d.shipmentId = f.shipmentId();
          d.invoiceId = ctx.ids().next();
          s.to(OrderSagaState.CAPTURING).command(new CapturePayment(d.paymentId)).deadline(now.plus(t.capture()), 0);
          return Outcome.APPLIED;
        }
        return st == OrderSagaState.AWAITING_FULFILMENT_ACK || st == OrderSagaState.FULFILLING ? Outcome.DEFERRED : Outcome.IGNORED;
      }
      case FulfilmentFailed f -> {
        if (!f.fulfilmentId().equals(d.fulfilmentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.AWAITING_FULFILMENT_ACK || st == OrderSagaState.FULFILLING || st == OrderSagaState.PACKED
            || attentionFrom(s, OrderSagaState.AWAITING_FULFILMENT_ACK)) {
          d.cancellationReason = CancellationReason.FULFILMENT_FAILED;
          d.cancellationDetail = f.reason();
          startCancelling(s, ctx, Compensation.VOID_PAYMENT, Compensation.RELEASE_RESERVATION);
          return Outcome.APPLIED;
        }
        return Outcome.IGNORED;
      }
      case FulfilmentCancelled f -> {
        return f.fulfilmentId().equals(d.fulfilmentId) ? compensationConfirmed(s, Compensation.CANCEL_FULFILMENT) : Outcome.IGNORED;
      }
      case PaymentCaptured p -> {
        if (!p.paymentId().equals(d.paymentId)) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.CAPTURING || attentionFrom(s, OrderSagaState.CAPTURING)) {
          if (d.captured) {
            return Outcome.IGNORED;
          }
          d.captured = true;
          d.capturedAmount = p.amount();
          if (d.carrier != null) {
            shipped(s, ctx);
          } else {
            // Shipping's ShipmentCreated is on another topic and may come later: wait for it.
            s.to(OrderSagaState.CAPTURING).deadline(now.plus(t.capture()), s.attempts);
          }
          return Outcome.APPLIED;
        }
        return Outcome.IGNORED;
      }
      case PaymentCaptureFailed p -> {
        if (!p.paymentId().equals(d.paymentId) || st != OrderSagaState.CAPTURING || d.captured) {
          return Outcome.IGNORED;
        }
        if (p.retryable() && d.captureRetries < SagaTimeouts.MAX_CAPTURE_RETRIES) {
          d.captureRetries++;
          s.deadline(now.plus(SagaTimeouts.CAPTURE_RETRY_BACKOFF), s.attempts);
        } else {
          attention(s, "capture failed after dispatch: " + p.reason());
        }
        return Outcome.APPLIED;
      }
      case ShipmentCreated c -> {
        if (!c.outbound() || d.carrier != null) {
          return Outcome.IGNORED;
        }
        d.carrier = c.carrier();
        d.trackingNumber = c.trackingNumber();
        if (d.shipmentId == null) {
          d.shipmentId = c.shipmentId();
        }
        if (st == OrderSagaState.CAPTURING && d.captured) {
          shipped(s, ctx);
        }
        return Outcome.APPLIED;
      }
      case ShipmentDelivered del -> {
        if (!del.outbound()) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.SHIPPED || attentionFrom(s, OrderSagaState.SHIPPED)) {
          s.to(OrderSagaState.DELIVERED)
              .event(new OrderEvent.Delivered(d.nextVersion(), del.deliveredAt(), del.deliveredAt().plus(SagaTimeouts.RETURN_WINDOW)))
              .deadline(null, 0);
          return Outcome.APPLIED;
        }
        return beforeShipped(st) ? Outcome.DEFERRED : Outcome.IGNORED;
      }
      case ShipmentException e -> {
        if (!e.outbound() || !e.lost()) {
          return Outcome.IGNORED;
        }
        if (st == OrderSagaState.SHIPPED) {
          attention(s, "shipment lost (" + e.code() + ")");
          return Outcome.APPLIED;
        }
        return beforeShipped(st) ? Outcome.DEFERRED : Outcome.IGNORED;
      }
      case Deadline dl -> {
        if (s.deadline == null || now.isBefore(s.deadline)) {
          return Outcome.IGNORED;
        }
        s.timeout = true;
        return onDeadline(s, ctx);
      }
      case OperatorRetry op -> {
        if (st != OrderSagaState.NEEDS_ATTENTION || d.attentionFrom == null) {
          return Outcome.IGNORED;
        }
        switch (d.attentionFrom) {
          case AWAITING_FULFILMENT_ACK, FULFILLING, PACKED -> {
            d.fulfilmentAttempt++;
            s.to(OrderSagaState.AWAITING_FULFILMENT_ACK)
                .command(new RequestFulfilment(d.fulfilmentId, d.fulfilmentAttempt))
                .deadline(now.plus(t.fulfilmentAck()), 0);
          }
          case CAPTURING -> {
            if (d.captured) {
              return Outcome.IGNORED;
            }
            d.captureRetries = 0;
            s.to(OrderSagaState.CAPTURING).command(new CapturePayment(d.paymentId)).deadline(now.plus(t.capture()), 0);
          }
          default -> {
            return Outcome.IGNORED;
          }
        }
        d.attentionFrom = null;
        d.attentionIssue = null;
        return Outcome.APPLIED;
      }
    }
  }

  private static Outcome onDeadline(Step s, Context ctx) {
    OrderSagaData d = s.data;
    SagaTimeouts t = ctx.timeouts();
    Instant now = ctx.now();
    switch (s.state) {
      case RESERVING_STOCK -> {
        if (s.attempts < SagaTimeouts.RESERVE_RESENDS) {
          s.command(new ReserveStock(d.reservationId, SagaTimeouts.RESERVATION_TTL_SECONDS)).deadline(now.plus(t.stock()), s.attempts + 1);
        } else {
          // The reply may have been lost: release in case something is held.
          d.cancellationReason = CancellationReason.SAGA_TIMEOUT;
          startCancelling(s, ctx, Compensation.RELEASE_RESERVATION);
        }
      }
      case AUTHORIZING_PAYMENT -> {
        if (s.attempts < SagaTimeouts.AUTHORIZE_RESENDS) {
          s.command(new AuthorizePayment(d.paymentId)).deadline(now.plus(t.payment()), s.attempts + 1);
        } else {
          d.cancellationReason = CancellationReason.SAGA_TIMEOUT;
          if (d.reservationExpired) {
            startCancelling(s, ctx, Compensation.VOID_PAYMENT);
          } else {
            startCancelling(s, ctx, Compensation.VOID_PAYMENT, Compensation.RELEASE_RESERVATION);
          }
        }
      }
      case COMMITTING_STOCK -> s.command(new CommitReservation(d.reservationId)).deadline(now.plus(t.commit()), s.attempts + 1);
      case AWAITING_FULFILMENT_ACK -> {
        if (d.fulfilmentAttempt < 1 + t.fulfilmentMaxResends()) {
          d.fulfilmentAttempt++;
          s.command(new RequestFulfilment(d.fulfilmentId, d.fulfilmentAttempt)).deadline(now.plus(t.fulfilmentAck()), s.attempts + 1);
        } else {
          attention(s, "warehouse did not acknowledge fulfilment after " + d.fulfilmentAttempt + " attempts");
        }
      }
      case FULFILLING, PACKED -> attention(s, d.authorizationExpiresAt != null && !now.isBefore(d.authorizationExpiresAt.minus(SagaTimeouts.AUTHORIZATION_SAFETY))
          ? "authorisation expires before dispatch" : "no dispatch within the deadline");
      case CAPTURING -> {
        if (d.captured) {
          attention(s, "captured but no shipment details from the carrier");
        } else {
          s.command(new CapturePayment(d.paymentId)).deadline(now.plus(t.capture()), s.attempts + 1);
        }
      }
      case SHIPPED -> attention(s, "not delivered within " + SagaTimeouts.SHIPPED_TIMEOUT.toDays() + " days");
      case CANCELLING -> {
        // Compensations must succeed: resend forever, with backoff (alerting is on the timeout metric).
        d.compensationAttempts++;
        resendCompensations(s, d);
        long factor = 1L << Math.min(d.compensationAttempts, 4);
        s.deadline(now.plus(t.compensation().multipliedBy(factor)), s.attempts + 1);
      }
      default -> {
        return Outcome.IGNORED;
      }
    }
    return Outcome.APPLIED;
  }

  private static void startCancelling(Step s, Context ctx, Compensation... compensations) {
    OrderSagaData d = s.data;
    s.to(OrderSagaState.CANCELLING);
    for (Compensation c : compensations) {
      d.outstanding.add(c);
    }
    d.compensationAttempts = 0;
    resendCompensations(s, d);
    s.deadline(ctx.now().plus(ctx.timeouts().compensation()), 0);
  }

  private static void resendCompensations(Step s, OrderSagaData d) {
    String reason = d.cancellationReason == null ? "cancelled" : d.cancellationReason.name();
    for (Compensation c : d.outstanding) {
      switch (c) {
        case RELEASE_RESERVATION -> s.command(new ReleaseReservation(d.reservationId, reason));
        case VOID_PAYMENT -> s.command(new VoidPayment(d.paymentId, reason));
        case CANCEL_FULFILMENT -> s.command(new CancelFulfilment(d.fulfilmentId, reason));
      }
    }
  }

  private static Outcome compensationConfirmed(Step s, Compensation c) {
    if (s.state != OrderSagaState.CANCELLING || !s.data.outstanding.remove(c)) {
      return Outcome.IGNORED;
    }
    if (s.data.outstanding.isEmpty()) {
      cancelled(s);
    }
    return Outcome.APPLIED;
  }

  private static void cancelled(Step s) {
    OrderSagaData d = s.data;
    s.to(OrderSagaState.CANCELLED)
        .event(new OrderEvent.Cancelled(d.nextVersion(), d.cancellationReason, d.cancellationDetail, d.paymentVoided))
        .deadline(null, 0);
    s.decisionReached = !d.confirmed;
  }

  private static void shipped(Step s, Context ctx) {
    OrderSagaData d = s.data;
    s.to(OrderSagaState.SHIPPED)
        .event(new OrderEvent.Shipped(d.nextVersion()))
        .event(new OrderEvent.InvoiceToIssue(d.nextVersion(), d.invoiceId))
        .deadline(ctx.now().plus(SagaTimeouts.SHIPPED_TIMEOUT), 0);
  }

  private static void attention(Step s, String issue) {
    OrderSagaData d = s.data;
    d.attentionFrom = s.state;
    d.attentionIssue = issue;
    OrderSagaState from = s.state;
    s.to(OrderSagaState.NEEDS_ATTENTION).event(new OrderEvent.RequiresAttention(d.nextVersion(), from, issue)).deadline(null, 0);
  }

  private static boolean attentionFrom(Step s, OrderSagaState from) {
    return s.state == OrderSagaState.NEEDS_ATTENTION && s.data.attentionFrom == from;
  }

  private static boolean beforeShipped(OrderSagaState st) {
    return st == OrderSagaState.AWAITING_FULFILMENT_ACK || st == OrderSagaState.FULFILLING || st == OrderSagaState.PACKED
        || st == OrderSagaState.CAPTURING;
  }

  private static Instant dispatchDeadline(OrderSagaData d, Context ctx) {
    Instant deadline = ctx.now().plus(ctx.timeouts().dispatch());
    if (d.authorizationExpiresAt != null) {
      Instant safety = d.authorizationExpiresAt.minus(SagaTimeouts.AUTHORIZATION_SAFETY);
      if (safety.isBefore(deadline)) {
        deadline = safety.isBefore(ctx.now()) ? ctx.now() : safety;
      }
    }
    return deadline;
  }

  /** Mutable working state of one decision. */
  private static final class Step {
    OrderSagaState state;
    OrderSagaData data;
    Instant deadline;
    int attempts;
    boolean timeout;
    boolean decisionReached;
    final List<OrderSagaCommand> commands = new ArrayList<>();
    final List<OrderEvent> events = new ArrayList<>();

    Step(OrderSagaState state, OrderSagaData data, Instant deadline, int attempts) {
      this.state = state;
      this.data = data;
      this.deadline = deadline;
      this.attempts = attempts;
    }

    static Decision ignored() {
      return new Decision(true, null, null, List.of(), List.of(), null, 0, false, false);
    }

    Step fork() {
      Step f = new Step(state, data.copy(), deadline, attempts);
      return f;
    }

    void absorb(Step other) {
      state = other.state;
      data = other.data;
      deadline = other.deadline;
      attempts = other.attempts;
      timeout |= other.timeout;
      decisionReached |= other.decisionReached;
      commands.addAll(other.commands);
      events.addAll(other.events);
    }

    Step to(OrderSagaState next) {
      state = next;
      return this;
    }

    Step command(OrderSagaCommand c) {
      commands.add(c);
      return this;
    }

    Step event(OrderEvent e) {
      events.add(e);
      return this;
    }

    Step deadline(Instant at, int stepAttempts) {
      deadline = at;
      attempts = stepAttempts;
      return this;
    }

    Decision decide() {
      return new Decision(false, state, data, List.copyOf(commands), List.copyOf(events), deadline, attempts, timeout, decisionReached);
    }
  }

}
