package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.common.header.Headers;
import org.apache.kafka.common.header.internals.RecordHeaders;

/**
 * The x-* headers added when a record is forwarded to a retry topic or the DLQ (architecture §8.1).
 * The x-original-* headers always describe the first source record, so they survive every hop.
 * {@code x-not-before} is an ISO-8601 UTC instant.
 */
public final class FailureHeaders {
  private FailureHeaders() {}

  static final int MAX_ERROR_MESSAGE = 1000;

  public static int previousAttempt(Headers headers) {
    String v = RecordProcessor.header(headers, EdaHeaders.X_RETRY_ATTEMPT);
    try {
      return v == null ? 0 : Integer.parseInt(v.trim());
    } catch (NumberFormatException e) {
      return 0;
    }
  }

  public static Headers build(
      ConsumerRecord<?, ?> record,
      String consumerGroup,
      RetryTopics.Destination destination,
      String errorClass,
      String errorMessage,
      Instant now) {
    Headers in = record.headers();
    String originalTopic = RecordProcessor.header(in, EdaHeaders.X_ORIGINAL_TOPIC);
    String originalPartition = RecordProcessor.header(in, EdaHeaders.X_ORIGINAL_PARTITION);
    String originalOffset = RecordProcessor.header(in, EdaHeaders.X_ORIGINAL_OFFSET);
    if (originalTopic == null) {
      originalTopic = record.topic();
      originalPartition = Integer.toString(record.partition());
      originalOffset = Long.toString(record.offset());
    }
    RecordHeaders out = new RecordHeaders();
    put(out, EdaHeaders.X_RETRY_ATTEMPT, Integer.toString(destination.attempt()));
    put(out, EdaHeaders.X_ORIGINAL_TOPIC, originalTopic);
    put(out, EdaHeaders.X_ORIGINAL_PARTITION, originalPartition);
    put(out, EdaHeaders.X_ORIGINAL_OFFSET, originalOffset);
    put(out, EdaHeaders.X_NOT_BEFORE, now.plus(destination.delay()).toString());
    put(out, EdaHeaders.X_ERROR_CLASS, errorClass);
    put(out, EdaHeaders.X_ERROR_MESSAGE, truncate(errorMessage));
    put(out, EdaHeaders.X_FAILED_CONSUMER_GROUP, consumerGroup);
    return out;
  }

  static String truncate(String message) {
    String m = message == null ? "" : message;
    return m.length() <= MAX_ERROR_MESSAGE ? m : m.substring(0, MAX_ERROR_MESSAGE);
  }

  private static void put(Headers headers, String name, String value) {
    headers.add(name, value.getBytes(StandardCharsets.UTF_8));
  }
}
