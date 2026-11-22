package com.edacommerce.edacommon.saga;

import com.edacommerce.edacommon.envelope.OutgoingMessage;
import java.time.Instant;
import java.util.List;
import org.springframework.lang.Nullable;

/**
 * The outcome of applying one trigger to a saga, as the engine persists it. Built by the service's
 * application layer from its pure domain decision.
 *
 * @param terminalOutcome metric outcome when the saga reaches a terminal state (DELIVERED, CANCELLED,
 *     REFUNDED, ...), else null
 * @param attention true when the saga enters a human-owned state (counted as MANUAL_REVIEW)
 * @param timeout true when the trigger was a deadline (counted on eda.saga.step.timeouts)
 * @param decisionReached true when this transition is the saga's "decision" (order: confirmed or
 *     cancelled), for the DECISION step metric
 */
public record SagaStep(
    boolean ignored,
    @Nullable String toState,
    @Nullable String data,
    @Nullable Instant deadlineAt,
    int stepAttempts,
    List<OutgoingMessage> messages,
    @Nullable String terminalOutcome,
    boolean attention,
    boolean timeout,
    boolean decisionReached) {

  public static SagaStep ignore() {
    return new SagaStep(true, null, null, null, 0, List.of(), null, false, false, false);
  }

  public boolean terminal() {
    return terminalOutcome != null;
  }
}
