package com.edacommerce.edacommon.saga;

import java.time.Instant;
import org.springframework.lang.Nullable;

/** One row of {@code saga_instance} (contracts/sql/common-tables.sql). {@code data} is JSON text. */
public record SagaRow(
    String sagaId,
    String sagaType,
    String state,
    String data,
    long version,
    @Nullable Instant deadlineAt,
    int stepAttempts,
    String correlationId,
    Instant createdAt,
    Instant updatedAt,
    @Nullable Instant completedAt) {}
