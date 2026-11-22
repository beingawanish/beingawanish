package com.edacommerce.edacommon.consumer;

import com.edacommerce.edacommon.envelope.EdaHeaders;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.apache.kafka.clients.consumer.Consumer;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.ConsumerRecords;
import org.apache.kafka.clients.consumer.OffsetAndMetadata;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.PartitionInfo;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.header.Header;
import org.apache.kafka.common.header.internals.RecordHeaders;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.lang.Nullable;

/**
 * DLQ peek and replay for one consumer group (admin.yaml /ops/dlq). Replay re-publishes into the
 * group's own first retry topic, never the original topic, so only this group sees the message again.
 * Replay commits its progress under group {@code G-dlq-replay}. A partition stops at the first record
 * that does not match the filter, so a filtered replay never skips (and so loses) other records.
 */
public class DlqService {
  private static final Duration POLL = Duration.ofMillis(500);

  private final String consumerGroup;
  private final ConsumerFactory<String, byte[]> consumerFactory;
  private final KafkaTemplate<String, byte[]> kafka;
  private final Clock clock;

  public DlqService(
      String consumerGroup,
      ConsumerFactory<String, byte[]> consumerFactory,
      KafkaTemplate<String, byte[]> kafka,
      Clock clock) {
    this.consumerGroup = consumerGroup;
    this.consumerFactory = consumerFactory;
    this.kafka = kafka;
    this.clock = clock;
  }

  /** Filter for a replay; null or empty fields match everything. */
  public record ReplayRequest(
      @Nullable Integer maxMessages, @Nullable String eventType, @Nullable List<String> eventIds) {
    int limit() {
      return maxMessages == null ? 100 : Math.max(0, Math.min(maxMessages, 10_000));
    }

    boolean matches(ConsumerRecord<String, byte[]> r) {
      if (eventType != null
          && !eventType.isBlank()
          && !eventType.equals(RecordProcessor.header(r.headers(), EdaHeaders.CE_TYPE))) {
        return false;
      }
      return eventIds == null
          || eventIds.isEmpty()
          || eventIds.contains(RecordProcessor.header(r.headers(), EdaHeaders.CE_ID));
    }
  }

  public List<DlqEntry> peek(int limit) {
    int max = Math.max(1, Math.min(limit, 500));
    List<DlqEntry> entries = new ArrayList<>();
    try (Consumer<String, byte[]> consumer = consumerFactory.createConsumer(null, null, "-dlq-peek", noCommit())) {
      List<TopicPartition> partitions = partitions(consumer);
      consumer.assign(partitions);
      consumer.seekToBeginning(partitions);
      Map<TopicPartition, Long> end = consumer.endOffsets(partitions);
      while (entries.size() < max && !reachedEnd(consumer, end)) {
        for (ConsumerRecord<String, byte[]> r : consumer.poll(POLL)) {
          if (entries.size() < max) {
            entries.add(toEntry(r));
          }
        }
      }
    }
    return entries;
  }

  /** Replays matching records into {@code G.retry.10s}; returns how many were replayed. */
  public int replay(ReplayRequest request) {
    int limit = request.limit();
    int replayed = 0;
    Properties props = new Properties();
    props.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
    props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
    try (Consumer<String, byte[]> consumer =
        consumerFactory.createConsumer(consumerGroup + "-dlq-replay", null, "-dlq-replay", props)) {
      List<TopicPartition> partitions = partitions(consumer);
      consumer.assign(partitions);
      Map<TopicPartition, OffsetAndMetadata> committed = consumer.committed(Set.copyOf(partitions));
      for (TopicPartition tp : partitions) {
        OffsetAndMetadata c = committed.get(tp);
        if (c == null) {
          consumer.seekToBeginning(List.of(tp));
        } else {
          consumer.seek(tp, c.offset());
        }
      }
      Map<TopicPartition, Long> end = consumer.endOffsets(partitions);
      Set<TopicPartition> stopped = new java.util.HashSet<>();
      while (replayed < limit && !reachedEnd(consumer, end) && stopped.size() < partitions.size()) {
        ConsumerRecords<String, byte[]> batch = consumer.poll(POLL);
        Map<TopicPartition, OffsetAndMetadata> progress = new HashMap<>();
        for (TopicPartition tp : batch.partitions()) {
          for (ConsumerRecord<String, byte[]> r : batch.records(tp)) {
            if (stopped.contains(tp) || replayed >= limit) {
              break;
            }
            if (!request.matches(r)) {
              stopped.add(tp);
              consumer.pause(List.of(tp));
              break;
            }
            forward(r);
            replayed++;
            progress.put(tp, new OffsetAndMetadata(r.offset() + 1));
          }
        }
        if (!progress.isEmpty()) {
          consumer.commitSync(progress);
        }
        // Re-seek partitions we stopped part-way, so a later replay starts at the first unreplayed record.
        for (TopicPartition tp : batch.partitions()) {
          OffsetAndMetadata p = progress.get(tp);
          if (p != null && stopped.contains(tp)) {
            consumer.seek(tp, p.offset());
          }
        }
      }
    }
    return replayed;
  }

  private void forward(ConsumerRecord<String, byte[]> r) {
    RecordHeaders headers = new RecordHeaders();
    for (Header h : r.headers()) {
      if (!h.key().equals(EdaHeaders.X_RETRY_ATTEMPT) && !h.key().equals(EdaHeaders.X_NOT_BEFORE)) {
        headers.add(h);
      }
    }
    headers.add(EdaHeaders.X_RETRY_ATTEMPT, "1".getBytes(StandardCharsets.UTF_8));
    headers.add(EdaHeaders.X_NOT_BEFORE, clock.instant().toString().getBytes(StandardCharsets.UTF_8));
    try {
      kafka
          .send(new ProducerRecord<>(RetryTopics.firstRetry(consumerGroup), null, r.key(), r.value(), headers))
          .get(30, TimeUnit.SECONDS);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new IllegalStateException("interrupted during DLQ replay", e);
    } catch (ExecutionException | TimeoutException e) {
      throw new IllegalStateException("DLQ replay forward failed", e);
    }
  }

  private List<TopicPartition> partitions(Consumer<String, byte[]> consumer) {
    List<PartitionInfo> infos = consumer.partitionsFor(RetryTopics.dlq(consumerGroup));
    if (infos == null) {
      return List.of();
    }
    return infos.stream().map(p -> new TopicPartition(p.topic(), p.partition())).toList();
  }

  private static boolean reachedEnd(Consumer<String, byte[]> consumer, Map<TopicPartition, Long> end) {
    for (Map.Entry<TopicPartition, Long> e : end.entrySet()) {
      if (!consumer.paused().contains(e.getKey()) && consumer.position(e.getKey()) < e.getValue()) {
        return false;
      }
    }
    return true;
  }

  private static Properties noCommit() {
    Properties p = new Properties();
    p.put(ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false");
    return p;
  }

  static DlqEntry toEntry(ConsumerRecord<String, byte[]> r) {
    return new DlqEntry(
        RecordProcessor.header(r.headers(), EdaHeaders.CE_ID),
        RecordProcessor.header(r.headers(), EdaHeaders.CE_TYPE),
        RecordProcessor.header(r.headers(), EdaHeaders.X_ORIGINAL_TOPIC),
        parseInt(RecordProcessor.header(r.headers(), EdaHeaders.X_ORIGINAL_PARTITION)),
        parseLong(RecordProcessor.header(r.headers(), EdaHeaders.X_ORIGINAL_OFFSET)),
        parseInt(RecordProcessor.header(r.headers(), EdaHeaders.X_RETRY_ATTEMPT)),
        RecordProcessor.header(r.headers(), EdaHeaders.X_ERROR_CLASS),
        RecordProcessor.header(r.headers(), EdaHeaders.X_ERROR_MESSAGE),
        Instant.ofEpochMilli(r.timestamp()));
  }

  @Nullable
  private static Integer parseInt(@Nullable String s) {
    try {
      return s == null ? null : Integer.valueOf(s);
    } catch (NumberFormatException e) {
      return null;
    }
  }

  @Nullable
  private static Long parseLong(@Nullable String s) {
    try {
      return s == null ? null : Long.valueOf(s);
    } catch (NumberFormatException e) {
      return null;
    }
  }
}
