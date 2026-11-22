package com.edacommerce.edacommon.saga;

import com.edacommerce.edacommon.http.ApiProblem;
import java.time.Instant;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.lang.Nullable;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

/** {@code GET /ops/sagas/{id}} and {@code POST /ops/sagas/{id}/retry-step} (admin.yaml). */
@RestController
public class SagaOpsController {

  /** admin.yaml SagaView. */
  public record SagaView(
      String sagaId,
      String sagaType,
      String state,
      long version,
      @Nullable Instant deadlineAt,
      int attempts,
      List<HistoryEntry> history) {}

  /** One transition in SagaView.history. */
  public record HistoryEntry(Instant at, String from, String to, String trigger, @Nullable String eventId) {}

  private final SagaRepository repository;
  private final SagaOperator operator;

  public SagaOpsController(SagaRepository repository, SagaOperator operator) {
    this.repository = repository;
    this.operator = operator;
  }

  @GetMapping("/ops/sagas/{sagaId}")
  public SagaView get(@PathVariable("sagaId") String sagaId) {
    SagaRow row = repository.find(sagaId).orElseThrow(() -> ApiProblem.notFound("saga " + sagaId));
    List<HistoryEntry> history =
        repository.history(sagaId).stream()
            .map(t -> new HistoryEntry(t.at(), t.fromState(), t.toState(), t.triggerType(), t.triggerId()))
            .toList();
    return new SagaView(
        row.sagaId(), row.sagaType(), row.state(), row.version(), row.deadlineAt(), row.stepAttempts(), history);
  }

  @PostMapping("/ops/sagas/{sagaId}/retry-step")
  public ResponseEntity<Void> retryStep(@PathVariable("sagaId") String sagaId) {
    return switch (operator.retryStep(sagaId)) {
      case ACCEPTED -> ResponseEntity.status(HttpStatus.ACCEPTED).build();
      case NOT_FOUND -> throw ApiProblem.notFound("saga " + sagaId);
      case TERMINAL -> throw ApiProblem.conflict("saga-terminal", "Saga is terminal", "saga " + sagaId + " is terminal");
      case NOT_APPLICABLE ->
          throw ApiProblem.conflict(
              "saga-not-retryable", "Nothing to retry", "saga " + sagaId + " has no step an operator can retry");
    };
  }
}
