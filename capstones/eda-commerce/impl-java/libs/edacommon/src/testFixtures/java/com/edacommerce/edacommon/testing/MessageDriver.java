package com.edacommerce.edacommon.testing;

import com.edacommerce.common.Envelope;
import com.edacommerce.edacommon.config.EdaProperties;
import com.edacommerce.edacommon.consumer.HandlerRegistry;
import com.edacommerce.edacommon.consumer.MessageHandler;
import com.edacommerce.edacommon.consumer.RecordProcessor;
import com.edacommerce.edacommon.envelope.Causation;
import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.OutgoingMessage;
import com.edacommerce.edacommon.ids.Ids;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.util.ArrayList;
import java.util.List;
import org.apache.avro.specific.SpecificRecord;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.context.ApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.lang.Nullable;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Drives a service's real message handlers through the real {@link RecordProcessor} (inbox, unit of
 * work, serde, tracing) without a broker, and reads what they appended to the outbox. This is how
 * service tests do "command in -> reply out with DB state asserted" in milliseconds.
 */
public class MessageDriver {

  /** A delivered record, kept so the exact same record can be redelivered. */
  public record Delivery(String eventId, ConsumerRecord<String, byte[]> record, Object outcome) {}

  /** One outbox row, decoded with the generated class named by event_type. */
  public record Published(
      String eventId,
      String topic,
      String key,
      String type,
      SpecificRecord record,
      String correlationId,
      @Nullable String causationId) {
    public Envelope envelope() {
      return Envelopes.of(record);
    }
  }

  private final RecordProcessor processor;
  private final AvroSerde serde;
  private final JdbcTemplate jdbc;
  private final Clock clock;

  @SuppressWarnings({"unchecked", "rawtypes"})
  public MessageDriver(ApplicationContext ctx) {
    List<MessageHandler<?>> handlers = new ArrayList<>((java.util.Collection) ctx.getBeansOfType(MessageHandler.class).values());
    this.serde = ctx.getBean(AvroSerde.class);
    this.jdbc = ctx.getBean(JdbcTemplate.class);
    this.clock = ctx.getBean(Clock.class);
    this.processor =
        new RecordProcessor(
            ctx.getBean(EdaProperties.class).getConsumerGroup(),
            new HandlerRegistry(handlers),
            ctx.getBean(Inbox.class),
            serde,
            ctx.getBean(TransactionTemplate.class),
            ctx.getBean(MessagingTracing.class),
            ctx.getBean(EdaMetrics.class),
            clock);
  }

  /** Delivers {@code record} as if published by {@code producer} with a fresh eventId. */
  public Delivery deliver(String topic, String key, SpecificRecord record) {
    return deliver(topic, key, record, key, null);
  }

  public Delivery deliver(
      String topic, String key, SpecificRecord record, String correlationId, @Nullable String causationId) {
    String eventId = Ids.newId();
    Envelope env =
        Envelopes.build(
            eventId,
            OutgoingMessage.of(topic, key, record, "Test", key, 1),
            new Causation(correlationId, causationId),
            "test-producer",
            clock.instant(),
            null,
            null);
    Envelopes.set(record, env);
    byte[] value = serde.serialize(topic, record);
    ConsumerRecord<String, byte[]> r = new ConsumerRecord<>(topic, 0, 0L, key, value);
    r.headers().add(EdaHeaders.CE_ID, eventId.getBytes(StandardCharsets.UTF_8));
    r.headers().add(EdaHeaders.CE_TYPE, env.getType().getBytes(StandardCharsets.UTF_8));
    return new Delivery(eventId, r, processor.process(r));
  }

  /** The same record again (same eventId): a Kafka redelivery. */
  public Delivery redeliver(Delivery d) {
    return new Delivery(d.eventId(), d.record(), processor.process(d.record()));
  }

  public RecordProcessor processor() {
    return processor;
  }

  public List<Published> published() {
    return jdbc.query(
        "SELECT id::text AS id, topic, aggregate_id, event_type, payload, correlation_id, causation_id"
            + " FROM outbox ORDER BY created_at, id",
        (rs, i) -> {
          String type = rs.getString("event_type");
          SpecificRecord rec = serde.deserialize(rs.getBytes("payload"), classOf(type));
          return new Published(
              rs.getString("id"),
              rs.getString("topic"),
              rs.getString("aggregate_id"),
              type,
              rec,
              rs.getString("correlation_id"),
              rs.getString("causation_id"));
        });
  }

  /** Records of {@code type} published for {@code key}, oldest first. */
  public <T extends SpecificRecord> List<T> published(Class<T> type, String key) {
    return published().stream()
        .filter(p -> p.key().equals(key) && type.isInstance(p.record()))
        .map(p -> type.cast(p.record()))
        .toList();
  }

  public List<Published> publishedFor(String key) {
    return published().stream().filter(p -> p.key().equals(key)).toList();
  }

  private static Class<? extends SpecificRecord> classOf(String type) {
    try {
      return Class.forName(type).asSubclass(SpecificRecord.class);
    } catch (ClassNotFoundException e) {
      throw new IllegalStateException(e);
    }
  }
}
