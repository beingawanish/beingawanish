package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.saga.DeadlineSweeper;
import com.edacommerce.edacommon.saga.SagaEngine;
import com.edacommerce.edacommon.saga.SagaRepository;
import com.edacommerce.edacommon.saga.SagaRow;
import com.edacommerce.edacommon.saga.SagaStep;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.RequiresPostgres;
import com.edacommerce.inventory.ReserveStock;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.OptimisticLockingFailureException;

@RequiresPostgres
class SagaKitIT {
  final DbFixture db = new DbFixture();
  final SagaRepository repo = new SagaRepository(db.jdbc);
  final SagaEngine engine = new SagaEngine(repo, db.outbox, db.tx, db.metrics, db.clock);

  @AfterEach
  void close() {
    db.close();
  }

  SagaStep to(String state, Instant deadline, OutgoingMessage... messages) {
    return new SagaStep(false, state, "{\"n\":1}", deadline, 0, List.of(messages), null, false, false, false);
  }

  OutgoingMessage reserve(String orderId) {
    return OutgoingMessage.of("inventory.commands.v1", orderId, GoldenFixtures.decode(ReserveStock.class), "Order", orderId, 1);
  }

  @Test
  void oneTransactionPerTransitionWithHistoryAndOutbox() {
    engine.handle("ORDER", "o1", "CheckoutSubmitted", "e1", null, "o1", (cur, now) -> to("RESERVING_STOCK", now.plusSeconds(30), reserve("o1")));
    engine.handle("ORDER", "o1", "StockReserved", "e2", null, null, (cur, now) -> {
      assertThat(cur.orElseThrow().state()).isEqualTo("RESERVING_STOCK");
      return to("AUTHORIZING_PAYMENT", now.plusSeconds(180));
    });
    assertThat(engine.handle("ORDER", "o1", "Late", "e3", null, null, (cur, now) -> SagaStep.ignore()))
        .isEqualTo(SagaEngine.Result.IGNORED);

    SagaRow row = repo.find("o1").orElseThrow();
    assertThat(row.state()).isEqualTo("AUTHORIZING_PAYMENT");
    assertThat(row.version()).isEqualTo(2);
    assertThat(row.correlationId()).isEqualTo("o1");
    assertThat(repo.history("o1")).extracting(t -> t.fromState() + ">" + t.toState() + ":" + t.seq())
        .containsExactly("NEW>RESERVING_STOCK:1", "RESERVING_STOCK>AUTHORIZING_PAYMENT:2");
    assertThat(db.count("SELECT count(*) FROM outbox WHERE topic = 'inventory.commands.v1'")).isEqualTo(1);
    assertThat(db.telemetry.metric("eda.saga.step.duration")).isPresent();
  }

  @Test
  void staleVersionsAreRejected() {
    engine.handle("ORDER", "o2", "Start", null, null, "o2", (cur, now) -> to("A", null));
    SagaRow row = repo.find("o2").orElseThrow();
    SagaRow next = new SagaRow(row.sagaId(), row.sagaType(), "B", row.data(), 2, null, 0, row.correlationId(), row.createdAt(), Instant.now(), null);
    db.tx.executeWithoutResult(s -> repo.update(next, 1));
    assertThatThrownBy(() -> db.tx.executeWithoutResult(s -> repo.update(next, 1)))
        .isInstanceOf(OptimisticLockingFailureException.class);
  }

  @Test
  void sweeperHandlesEachDueSagaOnceAcrossConcurrentSweepers() throws Exception {
    for (int i = 0; i < 20; i++) {
      String id = "s" + i;
      engine.handle("ORDER", id, "Start", null, null, id, (cur, now) -> to("WAITING", now.minusSeconds(1)));
    }
    engine.handle("ORDER", "future", "Start", null, null, "future", (cur, now) -> to("WAITING", now.plusSeconds(3600)));
    AtomicInteger handled = new AtomicInteger();
    CountDownLatch go = new CountDownLatch(1);
    DeadlineSweeper.DeadlineHandler handler =
        id -> {
          handled.incrementAndGet();
          engine.handle("ORDER", id, "DEADLINE", null, null, null, (cur, now) -> to("TIMED_OUT", null));
        };
    ExecutorService pool = Executors.newFixedThreadPool(3);
    List<Future<Integer>> runs =
        List.of(1, 2, 3).stream()
            .map(n -> pool.submit(() -> {
              go.await();
              return new DeadlineSweeper("ORDER", repo, db.tx, handler, db.metrics, db.clock).sweepOnce();
            }))
            .toList();
    go.countDown();
    int total = 0;
    for (Future<Integer> f : runs) {
      total += f.get(30, TimeUnit.SECONDS);
    }
    pool.shutdown();
    assertThat(total).isEqualTo(20);
    assertThat(handled.get()).isEqualTo(20);
    assertThat(db.count("SELECT count(*) FROM saga_instance WHERE state = 'TIMED_OUT'")).isEqualTo(20);
    assertThat(repo.find("future").orElseThrow().state()).isEqualTo("WAITING");
    assertThat(db.telemetry.metric("eda.saga.overdue")).isPresent();
  }
}
