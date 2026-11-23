package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import com.edacommerce.edacommon.errors.TransientException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.List;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.listener.AcknowledgingMessageListener;
import org.springframework.kafka.listener.ConcurrentMessageListenerContainer;
import org.springframework.kafka.listener.ContainerProperties;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.BackOff;

/**
 * Builds the two listener containers every consuming service runs (guide §10 "Kafka"):
 *
 * <ul>
 *   <li>the main container on the service's subscribed topics, group {@code G};
 *   <li>the retry container on {@code G.retry.*}, group {@code G-retry}, which waits until each
 *       record's {@code x-not-before} and then calls the same {@link RecordProcessor}.
 * </ul>
 *
 * Both use {@code AckMode.MANUAL_IMMEDIATE}: the offset is committed synchronously right after the
 * database transaction committed (or after the forward to a retry/DLQ topic was acknowledged).
 * Records of one partition are processed one at a time; parallelism comes from partitions.
 */
public final class ConsumerContainers {
  private ConsumerContainers() {}

  /** Longest single pause while waiting for x-not-before; keeps well inside max.poll.interval. */
  static final Duration MAX_WAIT_SLICE = Duration.ofSeconds(30);

  public static DefaultErrorHandler errorHandler(FailureForwarder forwarder, BackOff backOff) {
    DefaultErrorHandler handler = new DefaultErrorHandler(forwarder, backOff);
    // Only Transient is retried in place; RetryLater and NonRetryable are forwarded at once.
    handler.defaultFalse();
    handler.addRetryableExceptions(TransientException.class);
    handler.setCommitRecovered(true);
    handler.setAckAfterHandle(true);
    return handler;
  }

  public static ConcurrentMessageListenerContainer<String, byte[]> main(
      ConsumerFactory<String, byte[]> consumerFactory,
      List<String> topics,
      RecordProcessor processor,
      DefaultErrorHandler errorHandler,
      int concurrency,
      Duration shutdownTimeout) {
    AcknowledgingMessageListener<String, byte[]> listener =
        (record, ack) -> {
          processor.process(record);
          if (ack != null) {
            ack.acknowledge();
          }
        };
    return container(
        consumerFactory,
        topics,
        processor.consumerGroup(),
        listener,
        errorHandler,
        concurrency,
        shutdownTimeout);
  }

  public static ConcurrentMessageListenerContainer<String, byte[]> retry(
      ConsumerFactory<String, byte[]> consumerFactory,
      RecordProcessor processor,
      DefaultErrorHandler errorHandler,
      int concurrency,
      Duration shutdownTimeout,
      Clock clock) {
    String group = processor.consumerGroup();
    AcknowledgingMessageListener<String, byte[]> listener =
        (record, ack) -> {
          Duration wait = untilDue(record, clock.instant());
          if (!wait.isZero() && ack != null) {
            // Re-seek this record and pause the consumer (it keeps polling, so it keeps its
            // group membership) until the record is due.
            ack.nack(wait.compareTo(MAX_WAIT_SLICE) > 0 ? MAX_WAIT_SLICE : wait);
            return;
          }
          processor.process(record);
          if (ack != null) {
            ack.acknowledge();
          }
        };
    return container(
        consumerFactory,
        RetryTopics.retryTopics(group),
        group + "-retry",
        listener,
        errorHandler,
        concurrency,
        shutdownTimeout);
  }

  static Duration untilDue(ConsumerRecord<String, byte[]> record, Instant now) {
    String notBefore = RecordProcessor.header(record.headers(), EdaHeaders.X_NOT_BEFORE);
    if (notBefore == null) {
      return Duration.ZERO;
    }
    try {
      Duration d = Duration.between(now, Instant.parse(notBefore));
      return d.isNegative() ? Duration.ZERO : d;
    } catch (DateTimeParseException e) {
      return Duration.ZERO;
    }
  }

  private static ConcurrentMessageListenerContainer<String, byte[]> container(
      ConsumerFactory<String, byte[]> consumerFactory,
      List<String> topics,
      String groupId,
      AcknowledgingMessageListener<String, byte[]> listener,
      DefaultErrorHandler errorHandler,
      int concurrency,
      Duration shutdownTimeout) {
    ContainerProperties props = new ContainerProperties(topics.toArray(String[]::new));
    props.setGroupId(groupId);
    props.setAckMode(ContainerProperties.AckMode.MANUAL_IMMEDIATE);
    props.setMessageListener(listener);
    // SIGTERM: finish the in-flight record, commit, stop (do not drain the whole poll batch).
    props.setStopImmediate(true);
    props.setShutdownTimeout(shutdownTimeout.toMillis());
    props.setObservationEnabled(false);
    props.setSyncCommits(true);
    props.setClientId(groupId);
    ConcurrentMessageListenerContainer<String, byte[]> container =
        new ConcurrentMessageListenerContainer<>(consumerFactory, props);
    container.setConcurrency(concurrency);
    container.setCommonErrorHandler(errorHandler);
    container.setBeanName(groupId + "-container");
    return container;
  }
}
