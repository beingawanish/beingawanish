"""Metric contract (guide §8) and log shape / PII redaction (guide §6.4)."""

from __future__ import annotations

import io
import json

from edacommon.logging import configure_logging, get_logger, log_context
from edacommon.metrics import BUCKETS, PROMETHEUS_NAMES, EdaMetrics
from edacommon.testing import metrics_for_test
from edacommon.testing.fakes import collect


def _prom_name(name: str, unit: str, kind: str) -> str:
    """What the collector's Prometheus exporter does: dots -> underscores, unit suffix, _total."""
    base = name.replace(".", "_")
    suffix = {"s": "_seconds", "By": "_bytes"}.get(unit, "")
    if suffix and not base.endswith(suffix):
        base += suffix
    if kind == "counter":
        base += "_total"
    return base


def test_every_instrument_has_contract_name_unit_and_buckets() -> None:
    metrics, reader = metrics_for_test()
    m: EdaMetrics = metrics
    m.event_age(topic="t", consumer_group="g", event_type="e", seconds=0.3)
    m.processed(topic="t", consumer_group="g", event_type="e", outcome="success")
    m.handler_duration(consumer_group="g", event_type="e", seconds=0.01)
    m.dlq(consumer_group="g", event_type="e", error_class="NonRetryable")
    m.outbox_pending(3)
    m.saga_outcome(saga_type="ORDER", outcome="DELIVERED")
    m.saga_duration(saga_type="ORDER", outcome="DELIVERED", seconds=100)
    m.saga_step_duration(saga_type="ORDER", step="DECISION", seconds=1.2)
    m.saga_step_timeout(saga_type="ORDER", state="RESERVING_STOCK")
    m.saga_overdue(saga_type="ORDER", count=0)
    m.claimcheck_size(bucket="invoices", direction="put", size=12345)
    m.webhook(source="psp", outcome="accepted")
    data = collect(reader)
    kinds = {
        "eda.event.age": ("s", "histogram"), "eda.consumer.processed": ("{message}", "counter"),
        "eda.consumer.handler.duration": ("s", "histogram"), "eda.dlq.messages": ("{message}", "counter"),
        "eda.outbox.pending": ("{row}", "gauge"), "eda.saga.outcomes": ("{saga}", "counter"),
        "eda.saga.duration": ("s", "histogram"), "eda.saga.step.duration": ("s", "histogram"),
        "eda.saga.step.timeouts": ("{timeout}", "counter"), "eda.saga.overdue": ("{saga}", "gauge"),
        "eda.claimcheck.object.size": ("By", "histogram"), "eda.webhook.received": ("{webhook}", "counter"),
    }
    for name, (unit, kind) in kinds.items():
        assert name in data, name
        assert data[f"{name}#unit"] == [unit], name
        assert _prom_name(name, unit, kind) == PROMETHEUS_NAMES[name]
        if name in BUCKETS:
            (point,) = data[name]
            assert tuple(point.explicit_bounds) == BUCKETS[name], name
    (p,) = data["eda.consumer.processed"]
    assert dict(p.attributes) == {"topic": "t", "consumer_group": "g", "event_type": "e", "outcome": "success"}


def test_logs_are_json_with_required_fields_and_no_pii() -> None:
    buf = io.StringIO()
    configure_logging("order-svc", stream=buf)
    log = get_logger("t")
    with log_context(correlation_id="c-1", event_id="e-1", event_type="com.x.Y", order_id="o-1"):
        log.info("handled", contactEmail="jane.doe@example.com",
                 body={"shippingAddress": {"line1": "Invalidenstrasse 1"}, "sku": "SKU-1"})
        try:
            raise ValueError("boom")
        except ValueError:
            log.error("failed", exc_info=True)
    lines = [json.loads(x) for x in buf.getvalue().splitlines()]
    first, second = lines
    for k in ("ts", "level", "service", "impl", "msg", "correlation_id", "event_id", "event_type", "order_id"):
        assert k in first, k
    assert first["level"] == "INFO" and first["impl"] == "python" and first["service"] == "order-svc"
    assert first["ts"].endswith("Z")
    assert "contactEmail" not in first
    assert first["body"]["shippingAddress"] == "[REDACTED]" and first["body"]["sku"] == "SKU-1"
    assert "jane.doe@example.com" not in buf.getvalue() and "Invalidenstrasse" not in buf.getvalue()
    assert second["level"] == "ERROR" and second["error.class"] == "ValueError" and "boom" in second["error.message"]
    assert "Traceback" in second["error.stack"]
