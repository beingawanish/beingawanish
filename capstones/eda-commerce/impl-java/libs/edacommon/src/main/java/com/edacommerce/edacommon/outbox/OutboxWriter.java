package com.edacommerce.edacommon.outbox;

import com.edacommerce.common.Envelope;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.ids.IdGenerator;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import java.sql.Timestamp;
import java.time.Clock;
import java.time.Instant;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionSynchronizationManager;

/**
 * Appends events and commands to the transactional outbox (ADR-0003), inside the caller's database
 * transaction. The payload is serialised here, at write time, into the Confluent wire format; Debezium
 * (or the polling relay) then passes the bytes through untouched. The envelope's trace context is the
 * current span's, so the consumer's span becomes a child of the span that wrote the row.
 */
public class OutboxWriter {
  static final String INSERT =
      "INSERT INTO outbox (id, aggregate_type, aggregate_id, event_type, topic, payload, occurred_at,"
          + " producer, correlation_id, causation_id, traceparent, tracestate)"
          + " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";

  private final JdbcTemplate jdbc;
  private final AvroSerde serde;
  private final Clock clock;
  private final IdGenerator ids;
  private final String producer;

  public OutboxWriter(
      JdbcTemplate jdbc, AvroSerde serde, Clock clock, IdGenerator ids, String producer) {
    this.jdbc = jdbc;
    this.serde = serde;
    this.clock = clock;
    this.ids = ids;
    this.producer = producer;
  }

  /**
   * Fills in the message's envelope, serialises it and inserts the outbox row.
   *
   * @return the new message's eventId
   * @throws IllegalStateException when called outside a transaction (that would be a dual write)
   */
  public String append(OutgoingMessage message, Causation causation) {
    if (!TransactionSynchronizationManager.isActualTransactionActive()) {
      throw new IllegalStateException("OutboxWriter.append must run inside a database transaction");
    }
    String eventId = ids.newId();
    Instant now = clock.instant();
    MessagingTracing.TraceHeaders trace = MessagingTracing.current();
    Envelope envelope =
        Envelopes.build(eventId, message, causation, producer, now, trace.traceparent(), trace.tracestate());
    Envelopes.set(message.record(), envelope);
    byte[] payload = serde.serialize(message.topic(), message.record());
    jdbc.update(
        INSERT,
        UUID.fromString(eventId),
        message.aggregateType(),
        message.key(),
        envelope.getType(),
        message.topic(),
        payload,
        Timestamp.from(now),
        producer,
        causation.correlationId(),
        causation.causationId(),
        trace.traceparent(),
        trace.tracestate());
    return eventId;
  }
}
