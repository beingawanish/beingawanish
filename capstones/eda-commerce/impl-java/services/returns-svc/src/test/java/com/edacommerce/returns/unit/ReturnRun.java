package com.edacommerce.returns.unit;

import com.edacommerce.returns.domain.IdSource;
import com.edacommerce.returns.domain.InspectedItem;
import com.edacommerce.returns.domain.InspectionOutcome;
import com.edacommerce.returns.domain.ReturnItem;
import com.edacommerce.returns.domain.ReturnPolicy;
import com.edacommerce.returns.domain.ReturnReason;
import com.edacommerce.returns.domain.ReturnSaga;
import com.edacommerce.returns.domain.ReturnSagaData;
import com.edacommerce.returns.domain.ReturnSagaState;
import com.edacommerce.returns.domain.ReturnSagaTrigger;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/** Drives the pure returns saga like the application does (continuing through transient states). */
final class ReturnRun {
  static final Instant T0 = Instant.parse("2026-11-18T09:00:00Z");
  static final ReturnPolicy POLICY = new ReturnPolicy(50_000, Duration.ofDays(14));

  ReturnSagaState state;
  ReturnSagaData data;
  Instant deadline;
  int attempts;
  Instant now = T0;
  ReturnSaga.Decision last;
  final List<ReturnSaga.Decision> decisions = new ArrayList<>();
  final List<ReturnSagaState> path = new ArrayList<>();
  int ids;
  int rmas;

  final IdSource idSource =
      new IdSource() {
        @Override
        public String next() {
          return "id-" + (++ids);
        }

        @Override
        public String nextRma() {
          return String.format("RMA-2026-%06d", ++rmas);
        }
      };

  /** 2 x SKU-1001 at 129.99 (value 259.98 EUR, under the 500 EUR limit). */
  static ReturnRun started(ReturnReason reason) {
    return started(reason, List.of(new ReturnItem("l1", "SKU-1001", 2, 12_999)));
  }

  static ReturnRun started(ReturnReason reason, List<ReturnItem> items) {
    ReturnSagaData d = new ReturnSagaData();
    d.returnId = "r1";
    d.orderId = "o1";
    d.customerId = "c1";
    d.paymentId = "p1";
    d.currency = "EUR";
    d.reason = reason;
    d.items = new ArrayList<>(items);
    d.firstReturn = true;
    d.shippingFeeMinor = 499;
    d.warehouseId = "wh";
    ReturnRun r = new ReturnRun();
    r.take(ReturnSaga.start(d, r.ctx()));
    r.on(new ReturnSagaTrigger.Continue());
    return r;
  }

  ReturnSaga.Context ctx() {
    return new ReturnSaga.Context(now, idSource, POLICY);
  }

  /** Applies a trigger (and the automatic continuations); returns false if it was ignored. */
  boolean on(ReturnSagaTrigger t) {
    ReturnSaga.Decision d =
        ReturnSaga.apply(new ReturnSaga.Snapshot(state, data, deadline, attempts), t, ctx());
    if (d.ignored()) {
      last = d;
      return false;
    }
    take(d);
    while (d.continues()) {
      d =
          ReturnSaga.apply(
              new ReturnSaga.Snapshot(state, data, deadline, attempts),
              new ReturnSagaTrigger.Continue(),
              ctx());
      take(d);
    }
    return true;
  }

  private void take(ReturnSaga.Decision d) {
    last = d;
    decisions.add(d);
    state = d.state();
    data = d.data();
    deadline = d.deadlineAt();
    attempts = d.stepAttempts();
    path.add(state);
  }

  void advance(Duration by) {
    now = now.plus(by);
  }

  /** All commands since (and including) decision {@code from}. */
  List<Object> commandsSince(int from) {
    List<Object> out = new ArrayList<>();
    decisions.subList(from, decisions.size()).forEach(d -> out.addAll(d.commands()));
    return out;
  }

  List<Object> eventsSince(int from) {
    List<Object> out = new ArrayList<>();
    decisions.subList(from, decisions.size()).forEach(d -> out.addAll(d.events()));
    return out;
  }

  void received() {
    on(new ReturnSagaTrigger.ParcelReceived());
  }

  void inspected(InspectedItem... results) {
    on(new ReturnSagaTrigger.Inspected(List.of(results)));
  }

  static InspectedItem item(int q, InspectionOutcome o) {
    return new InspectedItem("l1", "SKU-1001", q, o);
  }
}
