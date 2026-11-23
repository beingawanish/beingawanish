package com.edacommerce.returns.application;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.errors.TransientException;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaOperator;
import com.edacommerce.edacommon.saga.SagaRow;
import com.edacommerce.edacommon.saga.SagaStep;
import com.edacommerce.returns.domain.Eligibility;
import com.edacommerce.returns.domain.IdSource;
import com.edacommerce.returns.domain.IneligibleReturnException;
import com.edacommerce.returns.domain.InspectedItem;
import com.edacommerce.returns.domain.OrderLine;
import com.edacommerce.returns.domain.Pickup;
import com.edacommerce.returns.domain.ReturnEvent;
import com.edacommerce.returns.domain.ReturnItem;
import com.edacommerce.returns.domain.ReturnOutcome;
import com.edacommerce.returns.domain.ReturnPolicy;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnSaga;
import com.edacommerce.returns.domain.ReturnSagaCommand;
import com.edacommerce.returns.domain.ReturnSagaData;
import com.edacommerce.returns.domain.ReturnSagaState;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.lang.Nullable;
import org.springframework.transaction.annotation.Transactional;

/**
 * The returns saga's use cases on the edacommon saga kit (the same engine as order-svc): one
 * transaction per trigger, in which the saga row, the transition row, the return's query row and
 * every outgoing command and event commit with the consumer's inbox row (guide §4.2). Transient
 * states (AUTHORIZED, REJECTED, EXPIRED) are passed through in the same transaction.
 */
public class ReturnsService implements SagaOperator {
  public static final String SAGA_TYPE = "RETURN";

  private final SagaEngine engine;
  private final EligibilityRepository eligibility;
  private final ReturnRepository returns;
  private final SagaDataCodec codec;
  private final IdGenerator ids;
  private final Clock clock;
  private final ReturnPolicy policy;
  private final Duration window;
  private final String defaultWarehouseId;

  public ReturnsService(
      SagaEngine engine,
      EligibilityRepository eligibility,
      ReturnRepository returns,
      SagaDataCodec codec,
      IdGenerator ids,
      Clock clock,
      ReturnPolicy policy,
      Duration window,
      String defaultWarehouseId) {
    this.engine = engine;
    this.eligibility = eligibility;
    this.returns = returns;
    this.codec = codec;
    this.ids = ids;
    this.clock = clock;
    this.policy = policy;
    this.window = window;
    this.defaultWarehouseId = defaultWarehouseId;
  }

  // ------------------------------------------------------------------ the saga

  /** POST /returns: eligibility check, then the saga starts (and may auto-approve at once). */
  @Transactional
  public ReturnView request(
      String customerId,
      String orderId,
      List<Eligibility.Requested> lines,
      ReturnReason reason,
      @Nullable String comment) {
    OrderEligibility order =
        eligibility
            .findOrderForUpdate(orderId)
            .filter(o -> o.customerId().equals(customerId))
            .orElseThrow(() -> new ReturnNotFoundException("order " + orderId));
    if ("CANCELLED".equals(order.status())) {
      throw new IneligibleReturnException(
          IneligibleReturnException.Reason.NOT_DELIVERED, "the order was cancelled");
    }
    List<ReturnItem> items =
        Eligibility.check(
            order.delivered(),
            order.windowEndsAt(),
            order.lines(),
            returns.heldQuantities(orderId),
            lines,
            clock.instant());
    if (order.paymentId() == null) {
      // Delivered implies confirmed: the OrderConfirmed fact is still on its way (retry topic).
      throw new TransientException("payment of order " + orderId + " not projected yet");
    }
    ReturnSagaData d = new ReturnSagaData();
    d.returnId = ids.newId();
    d.orderId = orderId;
    d.customerId = customerId;
    d.paymentId = order.paymentId();
    d.currency = order.currency();
    d.reason = reason;
    d.comment = comment;
    d.items = new ArrayList<>(items);
    d.firstReturn = !returns.anyForOrder(orderId);
    d.shippingFeeMinor = order.shippingFeeMinor();
    d.warehouseId = order.warehouseId() != null ? order.warehouseId() : defaultWarehouseId;
    engine.handle(
        SAGA_TYPE,
        d.returnId,
        "RETURN_REQUESTED",
        null,
        null,
        d.returnId,
        (current, now) -> toStep(ReturnSaga.start(d, context(now)), 0, now));
    apply(d.returnId, new ReturnSagaTrigger.Continue(), "CONTINUE", null, null);
    return returns.find(d.returnId).orElseThrow();
  }

  /** Any reply, event, decision, deadline or operator action for an existing return. */
  @Transactional
  public SagaEngine.Result handle(
      String returnId,
      ReturnSagaTrigger trigger,
      String triggerType,
      @Nullable String triggerId,
      @Nullable Causation causation) {
    return apply(returnId, trigger, triggerType, triggerId, causation);
  }

  private SagaEngine.Result apply(
      String returnId,
      ReturnSagaTrigger trigger,
      String triggerType,
      @Nullable String triggerId,
      @Nullable Causation causation) {
    AtomicReference<ReturnSaga.Decision> last = new AtomicReference<>();
    SagaEngine.Result result =
        engine.handle(
            SAGA_TYPE,
            returnId,
            triggerType,
            triggerId,
            causation,
            null,
            (current, now) -> {
              if (current.isEmpty()) {
                throw new RetryLaterException("no return saga " + returnId + " yet");
              }
              SagaRow row = current.get();
              ReturnSaga.Snapshot snapshot =
                  new ReturnSaga.Snapshot(
                      ReturnSagaState.valueOf(row.state()),
                      codec.read(row.data()),
                      row.deadlineAt(),
                      row.stepAttempts());
              ReturnSaga.Decision decision = ReturnSaga.apply(snapshot, trigger, context(now));
              if (decision.ignored()) {
                return SagaStep.ignore();
              }
              last.set(decision);
              return toStep(decision, row.version(), now);
            });
    ReturnSaga.Decision decision = last.get();
    if (result == SagaEngine.Result.APPLIED && decision != null && decision.continues()) {
      apply(returnId, new ReturnSagaTrigger.Continue(), "CONTINUE", triggerId, causation);
    }
    return result;
  }

  /** POST /ops/returns/{id}/decision. */
  @Transactional
  public ReturnView decide(String returnId, ReturnSagaTrigger.Decision.Kind kind, String note) {
    if (returns.find(returnId).isEmpty()) {
      throw new ReturnNotFoundException("return " + returnId);
    }
    SagaEngine.Result r =
        apply(returnId, new ReturnSagaTrigger.Decision(kind, note), "OPS_DECISION", null, null);
    if (r != SagaEngine.Result.APPLIED) {
      throw new NotWaitingForDecisionException(
          "return " + returnId + " is not waiting for " + kind);
    }
    return returns.find(returnId).orElseThrow();
  }

  public void onDeadline(String returnId) {
    apply(returnId, new ReturnSagaTrigger.Deadline(), "DEADLINE", null, null);
  }

  @Override
  @Transactional
  public RetryOutcome retryStep(String sagaId) {
    Optional<ReturnView> view = returns.find(sagaId);
    if (view.isEmpty()) {
      return RetryOutcome.NOT_FOUND;
    }
    if (List.of("REFUNDED", "PARTIALLY_REFUNDED", "REJECTED", "EXPIRED")
        .contains(view.get().status())) {
      return RetryOutcome.TERMINAL;
    }
    return apply(sagaId, new ReturnSagaTrigger.OperatorRetry(), "OPERATOR", null, null)
            == SagaEngine.Result.APPLIED
        ? RetryOutcome.ACCEPTED
        : RetryOutcome.NOT_APPLICABLE;
  }

  private ReturnSaga.Context context(Instant now) {
    return new ReturnSaga.Context(
        now,
        new IdSource() {
          @Override
          public String next() {
            return ids.newId();
          }

          @Override
          public String nextRma() {
            int year = now.atZone(ZoneOffset.UTC).getYear();
            return String.format("RMA-%d-%06d", year, returns.nextRmaSequence(year));
          }
        },
        policy);
  }

  private SagaStep toStep(ReturnSaga.Decision d, long currentVersion, Instant now) {
    ReturnSagaData data = d.data();
    List<OutgoingMessage> messages = new ArrayList<>();
    for (ReturnEvent e : d.events()) {
      messages.add(ReturnMessages.event(e, data, now));
    }
    Pickup pickup = null;
    for (ReturnSagaCommand c : d.commands()) {
      if (c instanceof ReturnSagaCommand.IssueReturnLabel && pickup == null) {
        pickup =
            eligibility
                .findOrder(data.orderId)
                .map(OrderEligibility::pickup)
                .orElseThrow(
                    () -> new IllegalStateException("return without order " + data.orderId));
      }
      messages.add(ReturnMessages.command(c, data, pickup, currentVersion + 1));
    }
    returns.save(view(d.state(), data), data.customerId, d.state().name(), holdsQuantity(d));
    return new SagaStep(
        false,
        d.state().name(),
        codec.write(data),
        d.deadlineAt(),
        d.stepAttempts(),
        messages,
        d.terminal() ? data.outcome.name() : null,
        d.attention(),
        d.timeout(),
        false);
  }

  /** A return that ended without the parcel coming back frees its quantities again. */
  private static boolean holdsQuantity(ReturnSaga.Decision d) {
    ReturnSagaData data = d.data();
    if (d.state() == ReturnSagaState.EXPIRED || data.outcome == ReturnOutcome.EXPIRED) {
      return false;
    }
    return !(data.outcome == ReturnOutcome.REJECTED && !data.received);
  }

  static ReturnView view(ReturnSagaState state, ReturnSagaData d) {
    List<ReturnView.Line> lines = new ArrayList<>();
    if (d.inspected.isEmpty()) {
      d.items.forEach(i -> lines.add(new ReturnView.Line(i.lineId(), i.sku(), i.quantity(), null)));
    } else {
      for (InspectedItem i : d.inspected) {
        lines.add(new ReturnView.Line(i.lineId(), i.sku(), i.quantity(), i.outcome().name()));
      }
    }
    boolean settled =
        state == ReturnSagaState.SETTLING
            || state == ReturnSagaState.REFUND_REVIEW
            || state == ReturnSagaState.CLOSED;
    return new ReturnView(
        d.returnId,
        d.orderId,
        d.rmaNumber,
        apiStatus(state, d),
        lines,
        settled && d.refundId != null ? d.refundAmountMinor : null,
        d.currency,
        d.label,
        d.parcelDueBy,
        d.requestedAt,
        d.reason.name(),
        d.comment);
  }

  /** Saga state -> returns.yaml Return.status. */
  static String apiStatus(ReturnSagaState state, ReturnSagaData d) {
    return switch (state) {
      case REQUESTED -> "REQUESTED";
      case MANUAL_REVIEW, REFUND_REVIEW -> "MANUAL_REVIEW";
      case AUTHORIZED -> "AUTHORIZED";
      case AWAITING_PARCEL -> "AWAITING_PARCEL";
      case AWAITING_INSPECTION -> "RECEIVED";
      case SETTLING -> "REFUNDING";
      case REJECTED -> "REJECTED";
      case EXPIRED -> "EXPIRED";
      case CLOSED ->
          switch (d.outcome) {
            case REFUNDED -> "REFUNDED";
            case PARTIALLY_REFUNDED -> "PARTIALLY_REFUNDED";
            case EXPIRED -> "EXPIRED";
            // Closed by staff without a refund: there is no CLOSED status in returns.yaml.
            case REJECTED, MANUAL_REVIEW -> "REJECTED";
          };
    };
  }

  // ------------------------------------------------------------------ eligibility projection

  @Transactional
  public void orderPlaced(
      String orderId,
      String customerId,
      String currency,
      List<OrderLine> lines,
      long totalMinor,
      Pickup pickup,
      long version) {
    long linesTotal = lines.stream().mapToLong(l -> l.unitPriceMinor() * l.quantity()).sum();
    eligibility.placed(
        orderId,
        customerId,
        currency,
        lines,
        Math.max(0, totalMinor - linesTotal),
        pickup,
        version);
  }

  @Transactional
  public void orderConfirmed(String orderId, String paymentId, long version) {
    if (!eligibility.confirmed(orderId, paymentId, version)) {
      throw new RetryLaterException("order " + orderId + " not projected yet");
    }
  }

  /** The window is RETURN_WINDOW_DAYS from delivery; returns-svc owns eligibility. */
  @Transactional
  public void orderDelivered(String orderId, Instant deliveredAt, long version) {
    if (!eligibility.delivered(orderId, deliveredAt, deliveredAt.plus(window), version)) {
      throw new RetryLaterException("order " + orderId + " not projected yet");
    }
  }

  @Transactional
  public void orderCancelled(String orderId, long version) {
    if (!eligibility.cancelled(orderId, version)) {
      throw new RetryLaterException("order " + orderId + " not projected yet");
    }
  }

  @Transactional
  public void fulfilmentAccepted(String orderId, String warehouseId) {
    if (!eligibility.warehouse(orderId, warehouseId)) {
      throw new RetryLaterException("order " + orderId + " not projected yet");
    }
  }

  // ------------------------------------------------------------------ queries

  public ReturnView get(String returnId, String customerId) {
    return returns
        .owner(returnId)
        .filter(customerId::equals)
        .flatMap(o -> returns.find(returnId))
        .orElseThrow(() -> new ReturnNotFoundException("return " + returnId));
  }

  /** What GET /orders/{orderId}/returns answers. */
  public record OrderReturns(
      List<ReturnView> returns, List<Returnable> returnable, Instant windowEndsAt) {}

  /** A line and the quantity still returnable. */
  public record Returnable(String lineId, String sku, int quantity) {}

  public OrderReturns forOrder(String orderId, String customerId) {
    OrderEligibility order =
        eligibility
            .findOrder(orderId)
            .filter(o -> o.customerId().equals(customerId))
            .orElseThrow(() -> new ReturnNotFoundException("order " + orderId));
    Map<String, Integer> left =
        Eligibility.returnable(order.lines(), returns.heldQuantities(orderId));
    boolean open =
        order.delivered()
            && order.windowEndsAt() != null
            && !clock.instant().isAfter(order.windowEndsAt());
    List<Returnable> returnable = new ArrayList<>();
    for (OrderLine l : order.lines()) {
      int q = open ? left.getOrDefault(l.lineId(), 0) : 0;
      if (q > 0) {
        returnable.add(new Returnable(l.lineId(), l.sku(), q));
      }
    }
    return new OrderReturns(returns.forOrder(orderId), returnable, order.windowEndsAt());
  }
}
