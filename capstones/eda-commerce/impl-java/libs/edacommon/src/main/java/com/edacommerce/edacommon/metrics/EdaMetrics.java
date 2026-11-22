package com.edacommerce.edacommon.metrics;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.metrics.DoubleHistogram;
import io.opentelemetry.api.metrics.LongCounter;
import io.opentelemetry.api.metrics.Meter;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * The metric contract of guide §8, registered once through the OpenTelemetry metrics API. Names,
 * units, attributes and bucket boundaries are part of the contract: the dashboard and the alert rules
 * query them, and the Python build registers the same ones. Bucket boundaries are given as advice on
 * the instrument, so no SDK view is needed. Never put ids on these attributes.
 */
public class EdaMetrics {

  public static final AttributeKey<String> TOPIC = AttributeKey.stringKey("topic");
  public static final AttributeKey<String> CONSUMER_GROUP = AttributeKey.stringKey("consumer_group");
  public static final AttributeKey<String> EVENT_TYPE = AttributeKey.stringKey("event_type");
  public static final AttributeKey<String> OUTCOME = AttributeKey.stringKey("outcome");
  public static final AttributeKey<String> ERROR_CLASS = AttributeKey.stringKey("error_class");
  public static final AttributeKey<String> SAGA_TYPE = AttributeKey.stringKey("saga_type");
  public static final AttributeKey<String> STEP = AttributeKey.stringKey("step");
  public static final AttributeKey<String> STATE = AttributeKey.stringKey("state");
  public static final AttributeKey<String> BUCKET = AttributeKey.stringKey("bucket");
  public static final AttributeKey<String> DIRECTION = AttributeKey.stringKey("direction");
  public static final AttributeKey<String> SOURCE = AttributeKey.stringKey("source");

  static final List<Double> EVENT_AGE_BUCKETS =
      List.of(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 1800.0);
  static final List<Double> HANDLER_BUCKETS =
      List.of(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0);
  static final List<Double> SAGA_DURATION_BUCKETS =
      List.of(
          1.0, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0, 3600.0, 21600.0, 86400.0, 604800.0, 2592000.0);
  static final List<Double> SAGA_STEP_BUCKETS =
      List.of(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 240.0, 600.0);
  static final List<Double> CLAIMCHECK_BUCKETS =
      List.of(1e3, 1e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, 5e6, 2e7);

  /** Processing outcomes, exactly the values of {@code eda.consumer.processed{outcome}}. */
  public enum Outcome {
    SUCCESS,
    DUPLICATE,
    IGNORED,
    RETRY,
    DLQ;

    public String label() {
      return name().toLowerCase(java.util.Locale.ROOT);
    }
  }

  private final DoubleHistogram eventAge;
  private final LongCounter processed;
  private final DoubleHistogram handlerDuration;
  private final LongCounter dlqMessages;
  private final AtomicLong outboxPending = new AtomicLong(-1);
  private final LongCounter sagaOutcomes;
  private final DoubleHistogram sagaDuration;
  private final DoubleHistogram sagaStepDuration;
  private final LongCounter sagaStepTimeouts;
  private final Map<String, AtomicLong> sagaOverdue = new ConcurrentHashMap<>();
  private final DoubleHistogram claimCheckSize;
  private final LongCounter webhookReceived;

  public EdaMetrics(OpenTelemetry openTelemetry) {
    Meter meter = openTelemetry.getMeter("com.edacommerce.edacommon");
    eventAge =
        meter
            .histogramBuilder("eda.event.age")
            .setUnit("s")
            .setDescription("Time from envelope.occurredAt to successful processing.")
            .setExplicitBucketBoundariesAdvice(EVENT_AGE_BUCKETS)
            .build();
    processed =
        meter
            .counterBuilder("eda.consumer.processed")
            .setUnit("{message}")
            .setDescription("Consumed records by outcome.")
            .build();
    handlerDuration =
        meter
            .histogramBuilder("eda.consumer.handler.duration")
            .setUnit("s")
            .setDescription("Handler time including the database transaction.")
            .setExplicitBucketBoundariesAdvice(HANDLER_BUCKETS)
            .build();
    dlqMessages =
        meter
            .counterBuilder("eda.dlq.messages")
            .setUnit("{message}")
            .setDescription("Records forwarded to the group's DLQ.")
            .build();
    meter
        .gaugeBuilder("eda.outbox.pending")
        .ofLongs()
        .setUnit("{row}")
        .setDescription("Unpublished outbox rows (polling relay only).")
        .buildWithCallback(
            m -> {
              long v = outboxPending.get();
              if (v >= 0) {
                m.record(v);
              }
            });
    sagaOutcomes =
        meter
            .counterBuilder("eda.saga.outcomes")
            .setUnit("{saga}")
            .setDescription("Sagas reaching a terminal or attention outcome.")
            .build();
    sagaDuration =
        meter
            .histogramBuilder("eda.saga.duration")
            .setUnit("s")
            .setDescription("Saga start to outcome.")
            .setExplicitBucketBoundariesAdvice(SAGA_DURATION_BUCKETS)
            .build();
    sagaStepDuration =
        meter
            .histogramBuilder("eda.saga.step.duration")
            .setUnit("s")
            .setDescription("Time spent per saga step; step=DECISION is start to confirmed/cancelled.")
            .setExplicitBucketBoundariesAdvice(SAGA_STEP_BUCKETS)
            .build();
    sagaStepTimeouts =
        meter
            .counterBuilder("eda.saga.step.timeouts")
            .setUnit("{timeout}")
            .setDescription("Saga step deadlines that fired.")
            .build();
    meter
        .gaugeBuilder("eda.saga.overdue")
        .ofLongs()
        .setUnit("{saga}")
        .setDescription("Sagas whose deadline passed more than 60 s ago (should always be 0).")
        .buildWithCallback(
            m ->
                sagaOverdue.forEach(
                    (type, value) -> m.record(value.get(), Attributes.of(SAGA_TYPE, type))));
    claimCheckSize =
        meter
            .histogramBuilder("eda.claimcheck.object.size")
            .setUnit("By")
            .setDescription("Size of claim-check objects.")
            .setExplicitBucketBoundariesAdvice(CLAIMCHECK_BUCKETS)
            .build();
    webhookReceived =
        meter
            .counterBuilder("eda.webhook.received")
            .setUnit("{webhook}")
            .setDescription("Inbound webhooks by outcome.")
            .build();
  }

  public void eventAge(String topic, String group, String eventType, Duration age) {
    eventAge.record(
        seconds(age), Attributes.of(TOPIC, topic, CONSUMER_GROUP, group, EVENT_TYPE, eventType));
  }

  public void processed(String topic, String group, String eventType, Outcome outcome) {
    processed.add(
        1,
        Attributes.of(
            TOPIC, topic, CONSUMER_GROUP, group, EVENT_TYPE, eventType, OUTCOME, outcome.label()));
  }

  public void handlerDuration(String group, String eventType, Duration duration) {
    handlerDuration.record(seconds(duration), Attributes.of(CONSUMER_GROUP, group, EVENT_TYPE, eventType));
  }

  public void dlq(String group, String eventType, String errorClass) {
    dlqMessages.add(
        1, Attributes.of(CONSUMER_GROUP, group, EVENT_TYPE, eventType, ERROR_CLASS, errorClass));
  }

  public void outboxPending(long rows) {
    outboxPending.set(rows);
  }

  public void sagaOutcome(String sagaType, String outcome) {
    sagaOutcomes.add(1, Attributes.of(SAGA_TYPE, sagaType, OUTCOME, outcome));
  }

  public void sagaDuration(String sagaType, String outcome, Duration duration) {
    sagaDuration.record(seconds(duration), Attributes.of(SAGA_TYPE, sagaType, OUTCOME, outcome));
  }

  public void sagaStepDuration(String sagaType, String step, Duration duration) {
    sagaStepDuration.record(seconds(duration), Attributes.of(SAGA_TYPE, sagaType, STEP, step));
  }

  public void sagaStepTimeout(String sagaType, String state) {
    sagaStepTimeouts.add(1, Attributes.of(SAGA_TYPE, sagaType, STATE, state));
  }

  public void sagaOverdue(String sagaType, long count) {
    sagaOverdue.computeIfAbsent(sagaType, k -> new AtomicLong()).set(count);
  }

  public void claimCheckSize(String bucket, String direction, long bytes) {
    claimCheckSize.record((double) bytes, Attributes.of(BUCKET, bucket, DIRECTION, direction));
  }

  public void webhookReceived(String source, String outcome) {
    webhookReceived.add(1, Attributes.of(SOURCE, source, OUTCOME, outcome));
  }

  private static double seconds(Duration d) {
    return Math.max(0, d.toNanos()) / 1_000_000_000.0;
  }
}
