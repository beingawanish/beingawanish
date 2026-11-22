package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.errors.ErrorClassifier;
import com.edacommerce.edacommon.metrics.EdaMetrics;
import java.time.Clock;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.Headers;
import org.apache.kafka.common.header.internals.RecordHeaders;
import org.springframework.kafka.core.KafkaOperations;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.support.KafkaHeaders;
import org.springframework.lang.Nullable;

/**
 * Forwards a failed record to the group's next retry topic or its DLQ (ADR-0007), built on Spring's
 * {@link DeadLetterPublishingRecoverer} with a destination resolver that produces our topic names
 * instead of Spring's {@code <topic>-retry-N}. The original key and value bytes are copied
 * unchanged (never re-serialised); Spring's {@code kafka_dlt-*} headers are suppressed and replaced
 * by the {@code x-*} headers both builds use. The send is awaited, so the offset is committed only
 * after the broker acknowledged the forward.
 */
public class FailureForwarder extends DeadLetterPublishingRecoverer {
  private final String consumerGroup;
  private final EdaMetrics metrics;

  public FailureForwarder(
      KafkaOperations<?, ?> template, String consumerGroup, EdaMetrics metrics, Clock clock) {
    super(
        template,
        (record, ex) -> new TopicPartition(destination(consumerGroup, record, ex).topic(), -1));
    this.consumerGroup = consumerGroup;
    this.metrics = metrics;
    setHeadersFunction(
        (record, ex) ->
            FailureHeaders.build(
                record,
                consumerGroup,
                destination(consumerGroup, record, ex),
                ErrorClassifier.errorClassName(ex),
                rootMessage(ex),
                clock.instant()));
    excludeHeader(HeaderNames.HeadersToAdd.values());
    setAppendOriginalHeaders(false);
    setFailIfSendResultIsError(true);
    setWaitForSendResultTimeout(Duration.ofSeconds(30));
    setVerifyPartition(false);
  }

  static RetryTopics.Destination destination(
      String group, ConsumerRecord<?, ?> record, Exception ex) {
    return RetryTopics.next(
        group, FailureHeaders.previousAttempt(record.headers()), ErrorClassifier.classify(ex));
  }

  @Override
  public void accept(ConsumerRecord<?, ?> record, @Nullable Consumer<?, ?> consumer, Exception ex) {
    super.accept(record, consumer, ex);
    String type = RecordProcessor.header(record.headers(), EdaHeaders.CE_TYPE);
    String eventType = type == null ? "unknown" : type;
    if (destination(consumerGroup, record, ex).deadLetter()) {
      metrics.dlq(consumerGroup, eventType, ErrorClassifier.errorClassName(ex));
      metrics.processed(record.topic(), consumerGroup, eventType, EdaMetrics.Outcome.DLQ);
    } else {
      metrics.processed(record.topic(), consumerGroup, eventType, EdaMetrics.Outcome.RETRY);
    }
  }

  /**
   * Keeps the original headers (ce_*, correlation, trace) in order and exactly one value per x-*
   * header: the one this hop computed, which the superclass appended last.
   */
  @Override
  protected ProducerRecord<Object, Object> createProducerRecord(
      ConsumerRecord<?, ?> record,
      TopicPartition topicPartition,
      Headers headers,
      @Nullable byte[] key,
      @Nullable byte[] value) {
    RecordHeaders out = new RecordHeaders();
    Map<String, Header> retryHeaders = new LinkedHashMap<>();
    for (Header h : headers) {
      if (EdaHeaders.isRetryHeader(h.key())) {
        retryHeaders.put(h.key(), h);
      } else if (!h.key().startsWith(KafkaHeaders.PREFIX)) {
        out.add(h);
      }
    }
    retryHeaders.values().forEach(out::add);
    Integer partition = topicPartition.partition() < 0 ? null : topicPartition.partition();
    return new ProducerRecord<>(
        topicPartition.topic(), partition, (Object) record.key(), (Object) record.value(), out);
  }

  private static String rootMessage(Throwable ex) {
    for (Throwable t = ex; t != null; t = t.getCause() == t ? null : t.getCause()) {
      if (t instanceof com.edacommerce.edacommon.errors.TransientException
          || t instanceof com.edacommerce.edacommon.errors.RetryLaterException
          || t instanceof com.edacommerce.edacommon.errors.NonRetryableException) {
        return t.getMessage() == null ? t.getClass().getSimpleName() : t.getMessage();
      }
    }
    return ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
  }
}
