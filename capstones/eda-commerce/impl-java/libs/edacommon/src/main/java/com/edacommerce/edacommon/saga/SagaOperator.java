package com.edacommerce.edacommon.saga;

/** Service hook behind {@code POST /ops/sagas/{id}/retry-step}. */
public interface SagaOperator {

  enum RetryOutcome {
    /** The current step's command was re-issued (new eventId, same business id). */
    ACCEPTED,
    NOT_FOUND,
    /** The saga is terminal; nothing to retry. */
    TERMINAL,
    /** The saga is not in a state an operator can retry. */
    NOT_APPLICABLE
  }

  RetryOutcome retryStep(String sagaId);
}
