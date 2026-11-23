package com.edacommerce.edacommon.consumer;

import java.time.Instant;

/** One parked record, as listed by {@code GET /ops/dlq} (admin.yaml DlqEntry). */
public record DlqEntry(
    String eventId,
    String eventType,
    String originalTopic,
    Integer originalPartition,
    Long originalOffset,
    Integer attempts,
    String errorClass,
    String errorMessage,
    Instant failedAt) {}
