package com.edacommerce.returns.domain;

import com.edacommerce.returns.domain.ReturnSagaTrigger.Decision.Kind;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * The returns saga as a pure function (ADR-0008): {@code (state, data, trigger, now) -> decision},
 * the executable form of architecture §6.1. It is a forward-recovery saga (§6.2): nothing after
 * inspection is compensated; refunds are retried on a schedule (1 min, 10 min, 1 h) with the same
 * refundId and then handed to a human (REFUND_REVIEW).
 *
 * <p>AUTHORIZED, REJECTED and EXPIRED are passed through within one trigger: a decision ending in
 * one of them has {@link Decision#continues()} set and the application applies {@link
 * ReturnSagaTrigger.Continue} in the same transaction, so every state of the diagram appears in the
 * transition log.
 */
public final class ReturnSaga {
  private ReturnSaga() {}

  /** Where the saga is now (the persisted row). */
  public record Snapshot(
      ReturnSagaState state, ReturnSagaData data, Instant deadlineAt, int stepAttempts) {}

  /** Inputs that are not saga state. */
  public record Context(Instant now, IdSource ids, ReturnPolicy policy) {}

  /** The outcome of one trigger. {@code ignored}: nothing to persist. */
  public record Decision(
      boolean ignored,
      ReturnSagaState state,
      ReturnSagaData data,
      List<ReturnSagaCommand> commands,
      List<ReturnEvent> events,
      Instant deadlineAt,
      int stepAttempts,
      boolean timeout) {

    public boolean continues() {
      return state != null && state.transient_();
    }

    public boolean terminal() {
      return state == ReturnSagaState.CLOSED;
    }

    public boolean attention() {
      return state != null && state.attention();
    }
  }

  /** POST /returns accepted: the saga starts in REQUESTED and emits ReturnRequested. */
  public static Decision start(ReturnSagaData data, Context ctx) {
    Step s = new Step(ReturnSagaState.REQUESTED, data.copy(), null, 0);
    s.data.requestedAt = ctx.now();
    s.event(new ReturnEvent.Requested(s.data.nextVersion()));
    return s.decide();
  }

  @SuppressWarnings("StatementSwitchToExpressionSwitch")
  public static Decision apply(Snapshot current, ReturnSagaTrigger trigger, Context ctx) {
    Step s =
        new Step(
            current.state(), current.data().copy(), current.deadlineAt(), current.stepAttempts());
    ReturnSagaData d = s.data;
    Instant now = ctx.now();
    ReturnSagaState st = s.state;
    switch (trigger) {
      case ReturnSagaTrigger.Continue c -> {
        switch (st) {
          case REQUESTED -> {
            if (d.valueMinor() <= ctx.policy().autoApproveLimitMinor()) {
              authorize(s, ctx);
            } else {
              s.to(ReturnSagaState.MANUAL_REVIEW).deadline(null, 0);
            }
          }
          case AUTHORIZED -> {
            d.shipmentId = ctx.ids().next();
            s.to(ReturnSagaState.AWAITING_PARCEL)
                .command(new ReturnSagaCommand.IssueReturnLabel(d.shipmentId))
                .command(new ReturnSagaCommand.ExpectReturn(d.parcelDueBy))
                .deadline(d.parcelDueBy, 0);
          }
          case REJECTED -> {
            d.outcome = ReturnOutcome.REJECTED;
            s.event(new ReturnEvent.Rejected(d.nextVersion(), d.rejectReason));
            close(s);
          }
          case EXPIRED -> {
            d.outcome = ReturnOutcome.EXPIRED;
            close(s);
          }
          default -> {
            return Step.ignored();
          }
        }
      }
      case ReturnSagaTrigger.Decision dec -> {
        d.decisionNote = dec.note();
        if (st == ReturnSagaState.MANUAL_REVIEW && dec.kind() == Kind.APPROVE) {
          authorize(s, ctx);
        } else if (st == ReturnSagaState.MANUAL_REVIEW && dec.kind() == Kind.REJECT) {
          d.rejectReason =
              dec.note() == null || dec.note().isBlank() ? "rejected after review" : dec.note();
          s.to(ReturnSagaState.REJECTED).deadline(null, 0);
        } else if (st == ReturnSagaState.REFUND_REVIEW && dec.kind() == Kind.RETRY_REFUND) {
          d.refundFailures = 0;
          s.to(ReturnSagaState.SETTLING)
              .command(new ReturnSagaCommand.RefundPayment(d.refundId, d.refundAmountMinor))
              .deadline(now.plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), 0);
        } else if (st == ReturnSagaState.REFUND_REVIEW && dec.kind() == Kind.CLOSE_WITHOUT_REFUND) {
          d.outcome = ReturnOutcome.MANUAL_REVIEW;
          close(s);
        } else {
          return Step.ignored(); // not waiting for this decision: the API answers 409
        }
      }
      case ReturnSagaTrigger.LabelIssued l -> {
        if (!l.shipmentId().equals(d.shipmentId) || d.label != null) {
          return Step.ignored();
        }
        d.label = l.label(); // stored whatever the state: the customer may still need it
      }
      case ReturnSagaTrigger.ParcelReceived r -> {
        if (st != ReturnSagaState.AWAITING_PARCEL || d.received) {
          return Step.ignored(); // a parcel after expiry is a matter for the warehouse and a human
        }
        d.received = true;
        s.to(ReturnSagaState.AWAITING_INSPECTION).deadline(null, 0);
      }
      case ReturnSagaTrigger.Inspected i -> {
        // ReturnReceived and ReturnInspected share a topic, but a retried record may reorder them.
        if (st != ReturnSagaState.AWAITING_INSPECTION && st != ReturnSagaState.AWAITING_PARCEL) {
          return Step.ignored();
        }
        d.received = true;
        settle(s, i.results(), ctx);
      }
      case ReturnSagaTrigger.ItemsRestocked r -> {
        if (!r.restockId().equals(d.restockId) || d.restocked) {
          return Step.ignored();
        }
        d.restocked = true;
        if (st == ReturnSagaState.SETTLING) {
          closeIfSettled(s);
        }
      }
      case ReturnSagaTrigger.RefundSucceeded r -> {
        if (!r.refundId().equals(d.refundId) || d.refunded) {
          return Step.ignored();
        }
        d.refunded = true;
        if (st == ReturnSagaState.REFUND_REVIEW) {
          // A "failed" refund that went through after all: carry on without the human.
          s.to(ReturnSagaState.SETTLING).deadline(now.plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), 0);
        }
        if (s.state == ReturnSagaState.SETTLING) {
          closeIfSettled(s);
        }
      }
      case ReturnSagaTrigger.RefundFailed f -> {
        if (!f.refundId().equals(d.refundId) || st != ReturnSagaState.SETTLING || d.refunded) {
          return Step.ignored();
        }
        d.refundFailures++;
        if (f.retryable() && d.refundFailures <= ReturnPolicy.REFUND_BACKOFF.size()) {
          // The deadline is the backoff; on it the refund is resent with the same refundId.
          s.deadline(now.plus(ReturnPolicy.REFUND_BACKOFF.get(d.refundFailures - 1)), s.attempts);
        } else {
          s.to(ReturnSagaState.REFUND_REVIEW).deadline(null, 0);
        }
      }
      case ReturnSagaTrigger.Deadline dl -> {
        if (s.deadline == null || now.isBefore(s.deadline)) {
          return Step.ignored();
        }
        s.timeout = true;
        switch (st) {
          case AWAITING_PARCEL -> s.to(ReturnSagaState.EXPIRED).deadline(null, 0);
          case SETTLING -> {
            resendOutstanding(s);
            s.deadline(now.plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), s.attempts + 1);
          }
          default -> {
            return Step.ignored();
          }
        }
      }
      case ReturnSagaTrigger.OperatorRetry op -> {
        switch (st) {
          case AWAITING_PARCEL ->
              s.command(new ReturnSagaCommand.IssueReturnLabel(d.shipmentId))
                  .command(new ReturnSagaCommand.ExpectReturn(d.parcelDueBy));
          case SETTLING -> {
            resendOutstanding(s);
            s.deadline(now.plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), 0);
          }
          case REFUND_REVIEW -> {
            d.refundFailures = 0;
            s.to(ReturnSagaState.SETTLING)
                .command(new ReturnSagaCommand.RefundPayment(d.refundId, d.refundAmountMinor))
                .deadline(now.plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), 0);
          }
          default -> {
            return Step.ignored();
          }
        }
      }
    }
    return s.decide();
  }

  private static void authorize(Step s, Context ctx) {
    ReturnSagaData d = s.data;
    if (d.rmaNumber == null) {
      d.rmaNumber = ctx.ids().nextRma();
    }
    d.parcelDueBy = ctx.now().plus(ctx.policy().parcelDue());
    s.to(ReturnSagaState.AUTHORIZED)
        .event(new ReturnEvent.Authorized(d.nextVersion()))
        .deadline(null, 0);
  }

  private static void settle(Step s, List<InspectedItem> reported, Context ctx) {
    ReturnSagaData d = s.data;
    d.inspected = new ArrayList<>(RefundPolicy.complete(d.items, reported));
    RefundPolicy.Settlement settlement =
        RefundPolicy.settle(d.items, d.inspected, d.reason, d.firstReturn, d.shippingFeeMinor);
    d.refundAmountMinor = settlement.amountMinor();
    d.partial = settlement.partial();
    d.restock = new java.util.LinkedHashMap<>(settlement.restock());
    if (!d.restock.isEmpty()) {
      d.restockId = ctx.ids().next();
      s.command(new ReturnSagaCommand.RestockItems(d.restockId, d.restock));
    } else {
      d.restocked = true; // nothing goes back on the shelf
    }
    if (d.refundAmountMinor > 0) {
      d.refundId = ctx.ids().next();
      s.to(ReturnSagaState.SETTLING)
          .command(new ReturnSagaCommand.RefundPayment(d.refundId, d.refundAmountMinor))
          .deadline(ctx.now().plus(ReturnPolicy.SETTLE_REPLY_TIMEOUT), 0);
    } else {
      d.rejectReason = "nothing refundable after inspection";
      s.to(ReturnSagaState.REJECTED).deadline(null, 0);
    }
  }

  private static void resendOutstanding(Step s) {
    ReturnSagaData d = s.data;
    if (!d.restocked && d.restockId != null) {
      s.command(new ReturnSagaCommand.RestockItems(d.restockId, d.restock));
    }
    if (!d.refunded) {
      s.command(new ReturnSagaCommand.RefundPayment(d.refundId, d.refundAmountMinor));
    }
  }

  private static void closeIfSettled(Step s) {
    ReturnSagaData d = s.data;
    if (!d.restocked || !d.refunded) {
      return;
    }
    d.outcome = d.partial ? ReturnOutcome.PARTIALLY_REFUNDED : ReturnOutcome.REFUNDED;
    s.event(new ReturnEvent.Refunded(d.nextVersion()));
    close(s);
  }

  private static void close(Step s) {
    s.to(ReturnSagaState.CLOSED)
        .event(new ReturnEvent.Closed(s.data.nextVersion(), s.data.outcome))
        .deadline(null, 0);
  }

  /** Mutable working state of one decision. */
  private static final class Step {
    ReturnSagaState state;
    final ReturnSagaData data;
    Instant deadline;
    int attempts;
    boolean timeout;
    final List<ReturnSagaCommand> commands = new ArrayList<>();
    final List<ReturnEvent> events = new ArrayList<>();

    Step(ReturnSagaState state, ReturnSagaData data, Instant deadline, int attempts) {
      this.state = state;
      this.data = data;
      this.deadline = deadline;
      this.attempts = attempts;
    }

    static Decision ignored() {
      return new Decision(true, null, null, List.of(), List.of(), null, 0, false);
    }

    Step to(ReturnSagaState next) {
      state = next;
      return this;
    }

    Step command(ReturnSagaCommand c) {
      commands.add(c);
      return this;
    }

    Step event(ReturnEvent e) {
      events.add(e);
      return this;
    }

    Step deadline(Instant at, int stepAttempts) {
      deadline = at;
      attempts = stepAttempts;
      return this;
    }

    Decision decide() {
      return new Decision(
          false,
          state,
          data,
          List.copyOf(commands),
          List.copyOf(events),
          deadline,
          attempts,
          timeout);
    }
  }
}
