package com.edacommerce.edacommon.saga;

import com.edacommerce.edacommon.metrics.EdaMetrics;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Fires {@code DEADLINE} triggers for due sagas (ADR-0008). Each due saga is locked with {@code FOR
 * UPDATE SKIP LOCKED} and handled in its own transaction, so several replicas sweep in parallel
 * without double work and one failing saga does not block the others. After each pass the {@code
 * eda.saga.overdue} gauge is set to the number of sagas more than 60 s past their deadline.
 */
public class DeadlineSweeper {
  private static final Logger log = LoggerFactory.getLogger(DeadlineSweeper.class);
  static final int MAX_PER_PASS = 100;
  static final Duration OVERDUE_GRACE = Duration.ofSeconds(60);

  /** The service's deadline handling: run the saga's DEADLINE trigger through the engine. */
  @FunctionalInterface
  public interface DeadlineHandler {
    void onDeadline(String sagaId);
  }

  private final String sagaType;
  private final SagaRepository repository;
  private final TransactionTemplate tx;
  private final DeadlineHandler handler;
  private final EdaMetrics metrics;
  private final Clock clock;

  public DeadlineSweeper(
      String sagaType,
      SagaRepository repository,
      TransactionTemplate tx,
      DeadlineHandler handler,
      EdaMetrics metrics,
      Clock clock) {
    this.sagaType = sagaType;
    this.repository = repository;
    this.tx = tx;
    this.handler = handler;
    this.metrics = metrics;
    this.clock = clock;
  }

  /** One pass; returns how many deadlines were handled. */
  public int sweepOnce() {
    List<String> seen = new ArrayList<>();
    int handled = 0;
    while (seen.size() < MAX_PER_PASS) {
      Instant now = clock.instant();
      Optional<String> sagaId;
      try {
        sagaId =
            Optional.ofNullable(
                tx.execute(
                    status -> {
                      Optional<String> due = repository.lockNextDue(sagaType, now, seen);
                      due.ifPresent(
                          id -> {
                            seen.add(id);
                            handler.onDeadline(id);
                          });
                      return due.orElse(null);
                    }));
      } catch (RuntimeException e) {
        log.warn("deadline handling failed; it is retried on the next pass", e);
        continue;
      }
      if (sagaId.isEmpty()) {
        break;
      }
      handled++;
    }
    metrics.sagaOverdue(
        sagaType, repository.countOverdue(sagaType, clock.instant().minus(OVERDUE_GRACE)));
    return handled;
  }
}
