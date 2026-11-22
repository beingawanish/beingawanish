package com.edacommerce.edacommon.it;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.RecordProcessor;
import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.errors.RetryLaterException;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.outbox.PollingOutboxRelay;
import com.edacommerce.edacommon.testing.GoldenFixtures;
import com.edacommerce.edacommon.testing.RequiresPostgres;
import com.edacommerce.inventory.CommitReservation;
import com.edacommerce.inventory.ReservationCommitted;
import io.opentelemetry.sdk.trace.data.SpanData;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

/** Guide §4.1 against a real database: inbox, unit of work, dispatch, tracing, crash replay. */
@RequiresPostgres
class RecordProcessorIT {
  static final String TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01";
  final DbFixture db = new DbFixture();
  final AtomicInteger calls = new AtomicInteger();
  volatile RuntimeException failWith;

  /** A participant: applies the effect once per business id and replies through the outbox. */
  final MessageHandler<CommitReservation> handler =
      new MessageHandler<>() {
        @Override
        public Class<CommitReservation> messageType() {
          return CommitReservation.class;
        }

        @Override
        public void handle(CommitReservation cmd, MessageContext ctx) {
          calls.incrementAndGet();
          if (failWith != null) {
            throw failWith;
          }
          db.jdbc.update(
              "INSERT INTO effect (id, n) VALUES (?, 1) ON CONFLICT (id) DO UPDATE SET n = effect.n + 1",
              cmd.getReservationId());
          ReservationCommitted reply =
              ReservationCommitted.newBuilder()
                  .setEnvelope(com.edacommerce.edacommon.envelope.Envelopes.placeholder())
                  .setOrderId(cmd.getOrderId())
                  .setReservationId(cmd.getReservationId())
                  .setCommittedAt(Instant.now())
                  .build();
          db.outbox.append(
              OutgoingMessage.of("inventory.events.v1", cmd.getOrderId(), reply, "Reservation", cmd.getReservationId(), 2),
              ctx.causation());
        }
      };

  final RecordProcessor processor =
      new RecordProcessor(
          "inventory-svc", new HandlerRegistry(List.of(handler)), db.inbox, db.serde, db.tx, db.tracing, db.metrics, db.clock);

  @AfterEach
  void close() {
    db.close();
  }

  ConsumerRecord<String, byte[]> record(String eventId, String type, byte[] value) {
    ConsumerRecord<String, byte[]> r = new ConsumerRecord<>("inventory.commands.v1", 4, 77L, "order-1", value);
    r.headers().add(EdaHeaders.CE_ID, eventId.getBytes(StandardCharsets.UTF_8));
    r.headers().add(EdaHeaders.CE_TYPE, type.getBytes(StandardCharsets.UTF_8));
    r.headers().add(EdaHeaders.TRACEPARENT, TRACEPARENT.getBytes(StandardCharsets.UTF_8));
    return r;
  }

  ConsumerRecord<String, byte[]> commit(String eventId) {
    CommitReservation cmd = GoldenFixtures.decode(CommitReservation.class);
    return record(eventId, "com.edacommerce.inventory.CommitReservation", db.serde.serialize("inventory.commands.v1", cmd));
  }

  @Test
  void processesOnceAndRepliesWithCausationAndTraceContext() {
    assertThat(processor.process(commit("e-1"))).isEqualTo(Outcome.SUCCESS);

    assertThat(db.count("SELECT n FROM effect")).isEqualTo(1);
    assertThat(db.count("SELECT count(*) FROM inbox WHERE message_id = 'e-1' AND consumer = 'inventory-svc'")).isEqualTo(1);
    var row = db.jdbc.queryForMap("SELECT causation_id, traceparent, correlation_id FROM outbox");
    assertThat(row.get("causation_id")).isEqualTo("e-1");
    SpanData consumerSpan = db.telemetry.spans().get(0);
    assertThat(consumerSpan.getParentSpanId()).isEqualTo("00f067aa0ba902b7");
    assertThat((String) row.get("traceparent"))
        .isEqualTo("00-" + consumerSpan.getTraceId() + "-" + consumerSpan.getSpanId() + "-01");
    assertThat(consumerSpan.getTraceId()).isEqualTo("4bf92f3577b34da6a3ce929d0e0e4736");
  }

  @Test
  void theSameMessageTwiceHasOneEffectAndCountsADuplicate() {
    assertThat(processor.process(commit("e-1"))).isEqualTo(Outcome.SUCCESS);
    // Crash simulation: the DB committed but the offset was never committed; Kafka redelivers.
    assertThat(processor.process(commit("e-1"))).isEqualTo(Outcome.DUPLICATE);

    assertThat(db.count("SELECT n FROM effect")).isEqualTo(1);
    assertThat(db.count("SELECT count(*) FROM outbox")).isEqualTo(1);
    assertThat(calls.get()).isEqualTo(1);
    var processed = db.telemetry.metric("eda.consumer.processed").orElseThrow();
    assertThat(processed.getLongSumData().getPoints())
        .anySatisfy(p -> assertThat(p.getAttributes().asMap().toString()).contains("outcome=duplicate"));
  }

  @Test
  void unknownTypesAreIgnoredWithoutDeserialising() {
    assertThat(processor.process(record("e-2", "com.edacommerce.inventory.Unheard", new byte[] {9, 9})))
        .isEqualTo(Outcome.IGNORED);
    assertThat(db.count("SELECT count(*) FROM inbox")).isZero();
  }

  @Test
  void undecodableValuesAreNonRetryableAndLeaveNoTrace() {
    assertThatThrownBy(() -> processor.process(record("e-3", "com.edacommerce.inventory.CommitReservation", new byte[] {0, 0, 0, 0, 1, 7})))
        .isInstanceOf(NonRetryableException.class);
    assertThat(db.count("SELECT count(*) FROM inbox")).isZero();
  }

  @Test
  void aFailingHandlerRollsBackTheInboxSoTheRetrySucceeds() {
    failWith = new IllegalStateException("downstream degraded");
    assertThatThrownBy(() -> processor.process(commit("e-4"))).isInstanceOf(RetryLaterException.class);
    assertThat(db.count("SELECT count(*) FROM inbox")).isZero();
    assertThat(db.count("SELECT count(*) FROM outbox")).isZero();

    failWith = null;
    assertThat(processor.process(commit("e-4"))).isEqualTo(Outcome.SUCCESS);
    assertThat(db.count("SELECT n FROM effect")).isEqualTo(1);
  }

  @Test
  void theReplyRowRelaysWithDebeziumHeaders() {
    processor.process(commit("e-5"));
    var row =
        db.jdbc.queryForObject(
            "SELECT id, aggregate_id, event_type, topic, payload, occurred_at, producer, correlation_id,"
                + " causation_id, traceparent, tracestate FROM outbox",
            (rs, i) ->
                new PollingOutboxRelay.OutboxRow(
                    rs.getObject("id", java.util.UUID.class), rs.getString("aggregate_id"), rs.getString("event_type"),
                    rs.getString("topic"), rs.getBytes("payload"), rs.getTimestamp("occurred_at").toInstant(),
                    rs.getString("producer"), rs.getString("correlation_id"), rs.getString("causation_id"),
                    rs.getString("traceparent"), rs.getString("tracestate")));
    assertThat(PollingOutboxRelay.toRecord(row).headers().lastHeader("causation_id").value())
        .isEqualTo("e-5".getBytes(StandardCharsets.UTF_8));
  }
}
