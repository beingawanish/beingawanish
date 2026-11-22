package com.edacommerce.edacommon.outbox;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.header.internals.RecordHeaders;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;
import org.springframework.lang.Nullable;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Fallback relay ({@code OUTBOX_RELAY=polling}, ADR-0003): publishes unpublished rows in insertion
 * order with exactly the headers the Debezium outbox router produces, then marks them published.
 * {@code FOR UPDATE SKIP LOCKED} lets several replicas run without double work; per-key order holds
 * within a batch, and across replicas only if one replica relays a given key at a time (run one
 * relay per service in production, or use Debezium).
 */
public class PollingOutboxRelay {
  private static final Logger log = LoggerFactory.getLogger(PollingOutboxRelay.class);
  static final String SELECT =
      "SELECT id, aggregate_id, event_type, topic, payload, occurred_at, producer, correlation_id,"
          + " causation_id, traceparent, tracestate FROM outbox WHERE published_at IS NULL"
          + " ORDER BY created_at, id LIMIT ? FOR UPDATE SKIP LOCKED";

  /** Debezium renders timestamptz columns as io.debezium.time.ZonedTimestamp (ISO-8601). */
  static final DateTimeFormatter CE_TIME = DateTimeFormatter.ISO_OFFSET_DATE_TIME;

  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final KafkaTemplate<String, byte[]> kafka;
  private final EdaMetrics metrics;
  private final int batchSize;

  public PollingOutboxRelay(
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      KafkaTemplate<String, byte[]> kafka,
      EdaMetrics metrics,
      int batchSize) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.kafka = kafka;
    this.metrics = metrics;
    this.batchSize = batchSize;
  }

  /** One relay pass. Returns the number of rows published. */
  public int relayOnce() {
    Integer published =
        tx.execute(
            status -> {
              List<OutboxRow> rows = jdbc.query(SELECT, (rs, i) -> OutboxRow.from(rs), batchSize);
              if (rows.isEmpty()) {
                return 0;
              }
              List<CompletableFuture<SendResult<String, byte[]>>> sends = new ArrayList<>();
              for (OutboxRow row : rows) {
                sends.add(kafka.send(toRecord(row)));
              }
              kafka.flush();
              for (CompletableFuture<SendResult<String, byte[]>> send : sends) {
                await(send);
              }
              UUID[] ids = rows.stream().map(OutboxRow::id).toArray(UUID[]::new);
              jdbc.update(
                  "UPDATE outbox SET published_at = now() WHERE id = ANY (?)",
                  ps -> ps.setArray(1, ps.getConnection().createArrayOf("uuid", ids)));
              return rows.size();
            });
    Long pending =
        jdbc.queryForObject("SELECT count(*) FROM outbox WHERE published_at IS NULL", Long.class);
    metrics.outboxPending(pending == null ? 0 : pending);
    return published == null ? 0 : published;
  }

  /** Same key, value and header set (and order) as the Debezium EventRouter configuration. */
  public static ProducerRecord<String, byte[]> toRecord(OutboxRow row) {
    RecordHeaders headers = new RecordHeaders();
    add(headers, EdaHeaders.ID, row.id().toString());
    add(headers, EdaHeaders.CE_ID, row.id().toString());
    add(headers, EdaHeaders.CE_TYPE, row.eventType());
    add(headers, EdaHeaders.CE_SOURCE, row.producer());
    add(headers, EdaHeaders.CE_TIME, CE_TIME.format(row.occurredAt().atOffset(ZoneOffset.UTC)));
    add(headers, EdaHeaders.CORRELATION_ID, row.correlationId());
    add(headers, EdaHeaders.CAUSATION_ID, row.causationId());
    add(headers, EdaHeaders.TRACEPARENT, row.traceparent());
    add(headers, EdaHeaders.TRACESTATE, row.tracestate());
    add(headers, EdaHeaders.CE_SPECVERSION, EdaHeaders.SPEC_VERSION);
    return new ProducerRecord<>(row.topic(), null, row.aggregateId(), row.payload(), headers);
  }

  private static void add(RecordHeaders headers, String name, @Nullable String value) {
    // Debezium places a header for every configured column, with a null value for SQL NULL.
    headers.add(name, value == null ? null : value.getBytes(StandardCharsets.UTF_8));
  }

  private static void await(CompletableFuture<SendResult<String, byte[]>> send) {
    try {
      send.get(30, TimeUnit.SECONDS);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("interrupted while publishing outbox rows", e);
    } catch (ExecutionException | TimeoutException e) {
      log.warn("outbox publish failed; the batch stays unpublished and is retried");
      throw new IllegalStateException("outbox publish failed", e);
    }
  }

  /** One outbox row as read by the relay. */
  @SuppressWarnings("ArrayRecordComponent") // bytes are opaque payloads, never compared
  public record OutboxRow(
      UUID id,
      String aggregateId,
      String eventType,
      String topic,
      byte[] payload,
      java.time.Instant occurredAt,
      String producer,
      String correlationId,
      @Nullable String causationId,
      @Nullable String traceparent,
      @Nullable String tracestate) {
    static OutboxRow from(java.sql.ResultSet rs) throws java.sql.SQLException {
      Timestamp occurred = rs.getTimestamp("occurred_at");
      return new OutboxRow(
          rs.getObject("id", UUID.class),
          rs.getString("aggregate_id"),
          rs.getString("event_type"),
          rs.getString("topic"),
          rs.getBytes("payload"),
          occurred.toInstant(),
          rs.getString("producer"),
          rs.getString("correlation_id"),
          rs.getString("causation_id"),
          rs.getString("traceparent"),
          rs.getString("tracestate"));
    }
  }
}
