package com.edacommerce.edacommon.consumer;

import com.edacommerce.common.Envelope;
import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.envelope.Envelopes;
import com.edacommerce.edacommon.envelope.MessageContext;
import com.edacommerce.edacommon.errors.ErrorClassifier;
import com.edacommerce.edacommon.errors.NonRetryableException;
import com.edacommerce.edacommon.inbox.Inbox;
import com.edacommerce.edacommon.logging.LogFields;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import com.edacommerce.edacommon.metrics.EdaMetrics.Outcome;
import com.edacommerce.edacommon.serde.AvroSerde;
import com.edacommerce.edacommon.tracing.MessagingTracing;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.apache.avro.Schema;
import org.apache.avro.specific.SpecificRecord;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.Headers;
import org.slf4j.MDC;
import org.springframework.lang.Nullable;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * The per-record algorithm of guide §4.1, without the Kafka plumbing around it (so it is testable
 * against a real database without a broker):
 *
 * <ol>
 *   <li>read {@code ce_type}; no handler: {@code ignored}, never deserialise;
 *   <li>in one transaction: inbox insert (conflict: {@code duplicate}), deserialise with the
 *       handler's reader schema, run the handler inside a consumer span; commit;
 *   <li>record event age and {@code success} after the commit.
 * </ol>
 *
 * Failures are re-thrown as exactly one of Transient / RetryLater / NonRetryable; the container's
 * error handler retries the first in place and forwards the others (see {@link FailureForwarder}).
 */
public class RecordProcessor {
  private final String consumerGroup;
  private final HandlerRegistry handlers;
  private final Inbox inbox;
  private final AvroSerde serde;
  private final TransactionTemplate tx;
  private final MessagingTracing tracing;
  private final EdaMetrics metrics;
  private final Clock clock;

  public RecordProcessor(
      String consumerGroup,
      HandlerRegistry handlers,
      Inbox inbox,
      AvroSerde serde,
      TransactionTemplate tx,
      MessagingTracing tracing,
      EdaMetrics metrics,
      Clock clock) {
    this.consumerGroup = consumerGroup;
    this.handlers = handlers;
    this.inbox = inbox;
    this.serde = serde;
    this.tx = tx;
    this.tracing = tracing;
    this.metrics = metrics;
    this.clock = clock;
  }

  public String consumerGroup() {
    return consumerGroup;
  }

  public Outcome process(ConsumerRecord<String, byte[]> record) {
    String type = header(record.headers(), EdaHeaders.CE_TYPE);
    if (type == null) {
      throw new NonRetryableException("record without ce_type header");
    }
    MessageHandler<?> handler = handlers.get(type);
    if (handler == null) {
      metrics.processed(record.topic(), consumerGroup, type, Outcome.IGNORED);
      return Outcome.IGNORED;
    }
    String eventId = header(record.headers(), EdaHeaders.CE_ID);
    if (eventId == null) {
      eventId = header(record.headers(), EdaHeaders.ID);
    }
    if (eventId == null) {
      throw new NonRetryableException("record without ce_id header");
    }
    final String messageId = eventId;
    Context parent = tracing.extract(record.headers());
    Span span = tracing.startConsumerSpan(record, consumerGroup, messageId, parent);
    long started = System.nanoTime();
    AtomicReference<Envelope> envelope = new AtomicReference<>();
    try (Scope scope = span.makeCurrent();
        LogFields.Scope logScope = LogFields.forMessage(messageId, type)) {
      Boolean fresh =
          tx.execute(
              status -> {
                if (!inbox.tryInsert(
                    messageId,
                    consumerGroup,
                    type,
                    record.topic(),
                    record.partition(),
                    record.offset())) {
                  status.setRollbackOnly();
                  return Boolean.FALSE;
                }
                SpecificRecord message = serde.deserialize(record.value(), handler.messageType());
                Envelope env = Envelopes.of(message);
                envelope.set(env);
                logScope.correlation(env.getCorrelationId(), orderIdOf(message));
                MessageContext context =
                    new MessageContext(
                        messageId,
                        type,
                        record.topic(),
                        record.partition(),
                        record.offset(),
                        record.key(),
                        consumerGroup,
                        env);
                invoke(handler, message, context);
                return Boolean.TRUE;
              });
      if (!Boolean.TRUE.equals(fresh)) {
        span.setAttribute("eda.outcome", Outcome.DUPLICATE.label());
        metrics.processed(record.topic(), consumerGroup, type, Outcome.DUPLICATE);
        return Outcome.DUPLICATE;
      }
      metrics.handlerDuration(consumerGroup, type, Duration.ofNanos(System.nanoTime() - started));
      Envelope env = envelope.get();
      if (env != null) {
        metrics.eventAge(
            record.topic(),
            consumerGroup,
            type,
            Duration.between(env.getOccurredAt(), clock.instant()));
      }
      metrics.processed(record.topic(), consumerGroup, type, Outcome.SUCCESS);
      return Outcome.SUCCESS;
    } catch (RuntimeException e) {
      span.recordException(e);
      span.setStatus(StatusCode.ERROR, ErrorClassifier.errorClassName(e));
      throw ErrorClassifier.normalise(e);
    } finally {
      span.end();
    }
  }

  @SuppressWarnings("unchecked")
  private static void invoke(
      MessageHandler<?> handler, SpecificRecord message, MessageContext ctx) {
    ((MessageHandler<SpecificRecord>) handler).handle(message, ctx);
  }

  @Nullable
  private static String orderIdOf(SpecificRecord message) {
    Schema.Field f = message.getSchema().getField("orderId");
    Object v = f == null ? null : message.get(f.pos());
    return v == null ? null : v.toString();
  }

  @Nullable
  public static String header(Headers headers, String name) {
    Header h = headers.lastHeader(name);
    return h == null || h.value() == null ? null : new String(h.value(), StandardCharsets.UTF_8);
  }

  /** For tests and the DLQ tooling: MDC is cleared by {@link LogFields.Scope}. */
  static String mdc(String key) {
    return MDC.get(key);
  }
}
