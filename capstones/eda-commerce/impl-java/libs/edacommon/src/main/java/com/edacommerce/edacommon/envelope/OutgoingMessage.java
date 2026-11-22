package com.edacommerce.edacommon.envelope;

import java.time.Instant;
import java.util.Objects;
import org.apache.avro.specific.SpecificRecord;
import org.springframework.lang.Nullable;

/**
 * A message to append to the outbox. The record's envelope is filled in by the outbox writer, so
 * callers only say where it goes, under which key, and which aggregate version it reflects.
 *
 * @param expiresAt commands only: a receiver acting after this instant must reject instead
 */
public record OutgoingMessage(
    String topic,
    String key,
    SpecificRecord record,
    String aggregateType,
    String aggregateId,
    long aggregateVersion,
    @Nullable Instant expiresAt) {

  public OutgoingMessage {
    Objects.requireNonNull(topic, "topic");
    Objects.requireNonNull(key, "key");
    Objects.requireNonNull(record, "record");
    Objects.requireNonNull(aggregateType, "aggregateType");
    Objects.requireNonNull(aggregateId, "aggregateId");
  }

  public static OutgoingMessage of(
      String topic,
      String key,
      SpecificRecord record,
      String aggregateType,
      String aggregateId,
      long aggregateVersion) {
    return new OutgoingMessage(
        topic, key, record, aggregateType, aggregateId, aggregateVersion, null);
  }

  public String type() {
    return record.getSchema().getFullName();
  }
}
