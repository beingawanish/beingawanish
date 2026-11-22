package com.edacommerce.edacommon.metrics;

import static org.assertj.core.api.Assertions.assertThat;

import com.edacommerce.edacommon.testing.TestTelemetry;
import io.opentelemetry.sdk.metrics.data.MetricData;
import io.opentelemetry.sdk.metrics.data.MetricDataType;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import org.junit.jupiter.api.Test;

/** Checklist "every metric in §8 appears with the exact name, unit, attributes and buckets". */
class EdaMetricsTest {

  @Test
  void registersTheMetricContract() {
    TestTelemetry t = new TestTelemetry();
    EdaMetrics m = new EdaMetrics(t.openTelemetry());
    m.eventAge("order.events.v1", "g", "T", Duration.ofMillis(120));
    m.processed("order.events.v1", "g", "T", EdaMetrics.Outcome.DUPLICATE);
    m.handlerDuration("g", "T", Duration.ofMillis(3));
    m.dlq("g", "T", "IOException");
    m.outboxPending(4);
    m.sagaOutcome("ORDER", "DELIVERED");
    m.sagaDuration("ORDER", "DELIVERED", Duration.ofMinutes(3));
    m.sagaStepDuration("ORDER", "DECISION", Duration.ofSeconds(2));
    m.sagaStepTimeout("ORDER", "RESERVING_STOCK");
    m.sagaOverdue("ORDER", 0);
    m.claimCheckSize("invoices", "put", 48_213);
    m.webhookReceived("psp", "duplicate");

    Map<String, MetricData> byName =
        t.collectMetrics().stream().collect(Collectors.toMap(MetricData::getName, x -> x));
    assertThat(byName.keySet())
        .containsExactlyInAnyOrder(
            "eda.event.age",
            "eda.consumer.processed",
            "eda.consumer.handler.duration",
            "eda.dlq.messages",
            "eda.outbox.pending",
            "eda.saga.outcomes",
            "eda.saga.duration",
            "eda.saga.step.duration",
            "eda.saga.step.timeouts",
            "eda.saga.overdue",
            "eda.claimcheck.object.size",
            "eda.webhook.received");

    assertUnit(byName, "eda.event.age", "s");
    assertUnit(byName, "eda.consumer.processed", "{message}");
    assertUnit(byName, "eda.outbox.pending", "{row}");
    assertUnit(byName, "eda.claimcheck.object.size", "By");
    assertUnit(byName, "eda.saga.outcomes", "{saga}");
    assertUnit(byName, "eda.saga.step.timeouts", "{timeout}");
    assertUnit(byName, "eda.webhook.received", "{webhook}");

    assertBuckets(byName, "eda.event.age", EdaMetrics.EVENT_AGE_BUCKETS);
    assertBuckets(byName, "eda.consumer.handler.duration", EdaMetrics.HANDLER_BUCKETS);
    assertBuckets(byName, "eda.saga.duration", EdaMetrics.SAGA_DURATION_BUCKETS);
    assertBuckets(byName, "eda.saga.step.duration", EdaMetrics.SAGA_STEP_BUCKETS);
    assertBuckets(byName, "eda.claimcheck.object.size", EdaMetrics.CLAIMCHECK_BUCKETS);
    assertThat(EdaMetrics.EVENT_AGE_BUCKETS)
        .containsExactly(
            0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0, 1800.0);

    var processed =
        byName.get("eda.consumer.processed").getLongSumData().getPoints().iterator().next();
    assertThat(processed.getAttributes().asMap().keySet().stream().map(Object::toString))
        .containsExactlyInAnyOrder("topic", "consumer_group", "event_type", "outcome");
    assertThat(processed.getAttributes().get(EdaMetrics.OUTCOME)).isEqualTo("duplicate");
    assertThat(byName.get("eda.outbox.pending").getType()).isEqualTo(MetricDataType.LONG_GAUGE);
  }

  static void assertUnit(Map<String, MetricData> m, String name, String unit) {
    assertThat(m.get(name).getUnit()).as(name).isEqualTo(unit);
  }

  static void assertBuckets(Map<String, MetricData> m, String name, List<Double> buckets) {
    var point = m.get(name).getHistogramData().getPoints().iterator().next();
    assertThat(point.getBoundaries()).as(name).isEqualTo(buckets);
  }
}
