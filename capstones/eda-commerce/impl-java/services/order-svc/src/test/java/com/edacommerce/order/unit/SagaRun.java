package com.edacommerce.order.unit;

import com.edacommerce.kernel.Money;
import com.edacommerce.order.domain.OrderEvent;
import com.edacommerce.order.domain.OrderSaga;
import com.edacommerce.order.domain.OrderSagaCommand;
import com.edacommerce.order.domain.OrderSagaData;
import com.edacommerce.order.domain.OrderSagaState;
import com.edacommerce.order.domain.OrderSagaTrigger;
import com.edacommerce.order.domain.SagaTimeouts;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Test driver: persists decisions in memory, like the saga engine does in the database. */
final class SagaRun {
  static final Instant T0 = Instant.parse("2026-11-18T09:00:00Z");
  final SagaTimeouts timeouts = SagaTimeouts.defaults();
  int idSeq;
  Instant now = T0;
  OrderSagaState state;
  OrderSagaData data;
  Instant deadline;
  int attempts;
  OrderSaga.Decision last;
  final List<OrderSagaCommand> allCommands = new ArrayList<>();
  final List<OrderEvent> allEvents = new ArrayList<>();

  OrderSaga.Context ctx() {
    return new OrderSaga.Context(now, () -> "id-" + (++idSeq), timeouts);
  }

  static SagaRun started() {
    SagaRun r = new SagaRun();
    r.record(OrderSaga.start("o1", Money.of(12999, "EUR"), r.ctx()));
    return r;
  }

  OrderSaga.Decision on(OrderSagaTrigger t) {
    OrderSaga.Decision d =
        OrderSaga.apply(new OrderSaga.Snapshot(state, data, deadline, attempts), t, ctx());
    if (!d.ignored()) {
      record(d);
    }
    last = d;
    return d;
  }

  OrderSaga.Decision deadlinePasses() {
    if (deadline != null) {
      now = deadline.plusMillis(1);
    }
    return on(new OrderSagaTrigger.Deadline());
  }

  void advance(Duration d) {
    now = now.plus(d);
  }

  private void record(OrderSaga.Decision d) {
    state = d.state();
    data = d.data();
    deadline = d.deadlineAt();
    attempts = d.stepAttempts();
    allCommands.addAll(d.commands());
    allEvents.addAll(d.events());
    last = d;
  }

  // ---- convenient replies carrying the current business ids
  OrderSagaTrigger reserved() {
    return new OrderSagaTrigger.StockReserved(data.reservationId);
  }

  OrderSagaTrigger authorized() {
    return new OrderSagaTrigger.PaymentAuthorized(data.paymentId, now.plus(Duration.ofDays(7)));
  }

  OrderSagaTrigger committed() {
    return new OrderSagaTrigger.ReservationCommitted(data.reservationId);
  }

  OrderSagaTrigger accepted() {
    return new OrderSagaTrigger.FulfilmentAccepted(data.fulfilmentId);
  }

  OrderSagaTrigger packed() {
    return new OrderSagaTrigger.OrderPacked(data.fulfilmentId);
  }

  OrderSagaTrigger dispatched() {
    return new OrderSagaTrigger.OrderDispatched(data.fulfilmentId, "ship-1");
  }

  OrderSagaTrigger shipmentCreated() {
    return new OrderSagaTrigger.ShipmentCreated("ship-1", true, "fake-carrier", "FC1");
  }

  OrderSagaTrigger captured() {
    return new OrderSagaTrigger.PaymentCaptured(data.paymentId, Money.of(12999, "EUR"));
  }

  OrderSagaTrigger delivered() {
    return new OrderSagaTrigger.ShipmentDelivered("ship-1", true, now);
  }

  SagaRun to(OrderSagaState target) {
    List<java.util.function.Supplier<OrderSagaTrigger>> path =
        List.of(
            this::reserved,
            this::authorized,
            this::committed,
            this::accepted,
            this::packed,
            this::shipmentCreated,
            this::dispatched,
            this::captured,
            this::delivered);
    for (var step : path) {
      if (state == target) {
        return this;
      }
      on(step.get());
    }
    if (state != target) {
      throw new IllegalStateException("did not reach " + target + ", at " + state);
    }
    return this;
  }
}
