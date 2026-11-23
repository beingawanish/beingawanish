package com.edacommerce.edacommon.saga;

import java.time.Instant;
import org.springframework.lang.Nullable;

/** One row of {@code saga_transition}: the audit log of a saga instance. */
public record SagaTransitionRow(
    String sagaId,
    long seq,
    String fromState,
    String toState,
    String triggerType,
    @Nullable String triggerId,
    Instant at) {}
