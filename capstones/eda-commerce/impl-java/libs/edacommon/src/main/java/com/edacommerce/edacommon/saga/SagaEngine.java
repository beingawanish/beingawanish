package com.edacommerce.edacommon.saga;

import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.outbox.OutboxWriter;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;
import org.springframework.lang.Nullable;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Applies one trigger to one saga in one transaction (guide §4.2, ADR-0008): lock the saga row,
 * decide, append the decision's commands and events to the outbox, save the row with version + 1,
 * append the transition row. When called from a message handler the transaction is the consumer's,
 * so the inbox insert commits atomically with all of it. Metrics are recorded after commit.
 */
public class SagaEngine {

  /** The service's decision function: current row (empty for a new saga) and now -> step. */
  @FunctionalInterface
  public interface Decider {
    SagaStep decide(Optional<SagaRow> current, Instant now);
  }

  /** What happened. */
  public enum Result {
    APPLIED,
    IGNORED
  }

  public static final String NEW_STATE = "NEW";

  private final SagaRepository repository;
  private final OutboxWriter outbox;
  private final TransactionTemplate tx;
  private final EdaMetrics metrics;
  private final Clock clock;

  public SagaEngine(
      SagaRepository repository,
      OutboxWriter outbox,
      TransactionTemplate tx,
      EdaMetrics metrics,
      Clock clock) {
    this.repository = repository;
    this.outbox = outbox;
    this.tx = tx;
    this.metrics = metrics;
    this.clock = clock;
  }

  /**
   * @param causation null for timers and operators: the saga's own correlation id is used
   * @param correlationIdIfNew correlation id stored for a saga created by this trigger
   */
  public Result handle(
      String sagaType,
      String sagaId,
      String triggerType,
      @Nullable String triggerId,
      @Nullable Causation causation,
      @Nullable String correlationIdIfNew,
      Decider decider) {
    Result result =
        tx.execute(
            status -> {
              Optional<SagaRow> current = repository.loadForUpdate(sagaId);
              Instant now = clock.instant();
              SagaStep step = decider.decide(current, now);
              if (step.ignored()) {
                return Result.IGNORED;
              }
              String correlationId =
                  current
                      .map(SagaRow::correlationId)
                      .orElseGet(() -> Objects.requireNonNull(correlationIdIfNew, "correlationIdIfNew"));
              Causation cause = causation != null ? causation : Causation.root(correlationId);
              for (OutgoingMessage message : step.messages()) {
                outbox.append(message, cause);
              }
              String from = current.map(SagaRow::state).orElse(NEW_STATE);
              String to = Objects.requireNonNull(step.toState(), "toState");
              long version = current.map(r -> r.version() + 1).orElse(1L);
              Instant createdAt = current.map(SagaRow::createdAt).orElse(now);
              SagaRow saved =
                  new SagaRow(
                      sagaId,
                      sagaType,
                      to,
                      Objects.requireNonNull(step.data(), "data"),
                      version,
                      step.deadlineAt(),
                      step.stepAttempts(),
                      correlationId,
                      createdAt,
                      now,
                      step.terminal() ? now : current.map(SagaRow::completedAt).orElse(null));
              if (current.isPresent()) {
                repository.update(saved, current.get().version());
              } else {
                repository.insert(saved);
              }
              repository.appendTransition(
                  new SagaTransitionRow(sagaId, version, from, to, triggerType, triggerId, now));
              Optional<Instant> enteredFrom =
                  current.isPresent() && !from.equals(to)
                      ? repository.enteredStateAt(sagaId, from)
                      : Optional.empty();
              afterCommit(() -> recordMetrics(sagaType, from, to, step, createdAt, enteredFrom, now));
              return Result.APPLIED;
            });
    return result == null ? Result.IGNORED : result;
  }

  private void recordMetrics(
      String sagaType,
      String from,
      String to,
      SagaStep step,
      Instant createdAt,
      Optional<Instant> enteredFrom,
      Instant now) {
    enteredFrom.ifPresent(at -> metrics.sagaStepDuration(sagaType, from, Duration.between(at, now)));
    if (step.decisionReached()) {
      metrics.sagaStepDuration(sagaType, "DECISION", Duration.between(createdAt, now));
    }
    if (step.timeout()) {
      metrics.sagaStepTimeout(sagaType, from);
    }
    if (step.attention() && !from.equals(to)) {
      metrics.sagaOutcome(sagaType, "MANUAL_REVIEW");
    }
    if (step.terminal()) {
      metrics.sagaOutcome(sagaType, step.terminalOutcome());
      metrics.sagaDuration(sagaType, step.terminalOutcome(), Duration.between(createdAt, now));
    }
  }

  private static void afterCommit(Runnable action) {
    if (TransactionSynchronizationManager.isSynchronizationActive()) {
      TransactionSynchronizationManager.registerSynchronization(
          new TransactionSynchronization() {
            @Override
            public void afterCommit() {
              action.run();
            }
          });
    } else {
      action.run();
    }
  }
}
