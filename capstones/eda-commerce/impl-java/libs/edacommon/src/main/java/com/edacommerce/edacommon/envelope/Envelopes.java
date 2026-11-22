package com.edacommerce.edacommon.envelope;

import com.edacommerce.common.Envelope;
import java.time.Instant;
import org.apache.avro.Schema;
import org.apache.avro.specific.SpecificRecord;
import org.springframework.lang.Nullable;

/** Builds and reads {@link Envelope}s with the rules of guide §4 ("envelope"). */
public final class Envelopes {
  private Envelopes() {}

  /**
   * The envelope for an outgoing message: {@code type} is the Avro full name, {@code partitionKey} is
   * the record key, the causation id the triggering eventId, {@code version} the topic's major
   * version.
   */
  public static Envelope build(
      String eventId,
      OutgoingMessage message,
      Causation causation,
      String producer,
      Instant occurredAt,
      @Nullable String traceparent,
      @Nullable String tracestate) {
    return Envelope.newBuilder()
        .setEventId(eventId)
        .setType(message.type())
        .setVersion(versionOfTopic(message.topic()))
        .setOccurredAt(occurredAt)
        .setCorrelationId(causation.correlationId())
        .setCausationId(causation.causationId())
        .setTraceparent(traceparent)
        .setTracestate(tracestate)
        .setProducer(producer)
        .setPartitionKey(message.key())
        .setAggregateType(message.aggregateType())
        .setAggregateId(message.aggregateId())
        .setAggregateVersion(message.aggregateVersion())
        .setTenantId(null)
        .setExpiresAt(message.expiresAt())
        .build();
  }

  /** {@code order.events.v1} -> 1. */
  public static int versionOfTopic(String topic) {
    int i = topic.lastIndexOf(".v");
    if (i < 0) {
      throw new IllegalArgumentException("topic has no .vN suffix: " + topic);
    }
    return Integer.parseInt(topic.substring(i + 2));
  }

  /** Every contract record has {@code envelope} as its first field (lint rule in contracts.py). */
  public static Envelope of(SpecificRecord record) {
    Schema.Field field = record.getSchema().getField("envelope");
    if (field == null) {
      throw new IllegalArgumentException(record.getSchema().getFullName() + " has no envelope");
    }
    return (Envelope) record.get(field.pos());
  }

  public static void set(SpecificRecord record, Envelope envelope) {
    Schema.Field field = record.getSchema().getField("envelope");
    if (field == null) {
      throw new IllegalArgumentException(record.getSchema().getFullName() + " has no envelope");
    }
    record.put(field.pos(), envelope);
  }

  /**
   * A placeholder envelope for building records before the outbox writer fills in the real one.
   * Avro builders refuse to build a record with a missing non-null field.
   */
  public static Envelope placeholder() {
    return Envelope.newBuilder()
        .setEventId("")
        .setType("")
        .setOccurredAt(Instant.EPOCH)
        .setCorrelationId("")
        .setProducer("")
        .setPartitionKey("")
        .setAggregateType("")
        .setAggregateId("")
        .build();
  }
}
