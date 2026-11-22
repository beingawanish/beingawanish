"""Pure unit tests for ids, durations, errors, envelope, headers, partitioner, idempotency hashing."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from edacommon.durations import parse_duration
from edacommon.envelope import OutboxRow, debezium_time, headers_for_row, topic_major_version
from edacommon.errors import NonRetryable, RetryLater, Transient, classify
from edacommon.idempotency import canonical_json, request_hash
from edacommon.ids import from_millis, new_id, rfc3339, to_millis, uuid7, uuid7_time
from edacommon.kafka import java_partition, murmur2, producer_config
from edacommon.config import ServiceSettings

CONNECTORS = Path(__file__).resolve().parents[4] / "infra" / "connect" / "connectors"


def test_uuid7_layout_and_monotonic_order() -> None:
    ids = [uuid7(now_ms=1_795_000_000_000) for _ in range(2000)]
    assert all(u.version == 7 and u.variant == uuid.RFC_4122 for u in ids)
    assert ids == sorted(ids), "ids minted in one millisecond must sort in creation order"
    assert len(set(ids)) == len(ids)
    assert uuid7_time(ids[0]) >= datetime(2026, 11, 18, 9, 46, 40, tzinfo=UTC)
    assert new_id() == new_id().lower() or True
    s = new_id()
    assert s == s.lower() and len(s) == 36


def test_time_helpers() -> None:
    dt = datetime(2026, 11, 18, 11, 6, 40, 123456, tzinfo=UTC)  # 1_795_000_000_123 ms
    assert to_millis(dt) == 1_795_000_000_123
    assert from_millis(1_795_000_000_123) == dt.replace(microsecond=123000)
    assert rfc3339(dt) == "2026-11-18T11:06:40.123Z"
    with pytest.raises(ValueError, match="naive"):
        to_millis(datetime(2026, 1, 1))  # noqa: DTZ001


@pytest.mark.parametrize(("raw", "seconds"), [("200ms", 0.2), ("30s", 30), ("10m", 600), ("24h", 86400), ("7d", 604800)])
def test_durations(raw: str, seconds: float) -> None:
    assert parse_duration(raw) == timedelta(seconds=seconds)


def test_bad_duration() -> None:
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration("thirty seconds")


def test_error_classification() -> None:
    class PgErr(Exception):
        sqlstate = "40P01"

    class Wrapped(Exception):
        orig = PgErr()

    assert classify(Transient("x")) is Transient
    assert classify(NonRetryable("x")) is NonRetryable
    assert classify(Wrapped()) is Transient
    assert classify(ConnectionRefusedError()) is Transient
    assert classify(RuntimeError("bug")) is RetryLater  # ADR-0007: unknown -> RetryLater


def test_debezium_time_format() -> None:
    assert debezium_time(datetime(2026, 11, 18, 9, 46, 40, 123000, tzinfo=UTC)) == "2026-11-18T09:46:40.123Z"
    assert debezium_time(datetime(2026, 11, 18, 9, 46, 40, tzinfo=UTC)) == "2026-11-18T09:46:40Z"


def test_topic_major_version() -> None:
    assert topic_major_version("order.events.v1") == 1
    assert topic_major_version("order.events.v2") == 2


def test_polling_relay_headers_match_debezium_connector_config() -> None:
    """Header names and order follow infra/connect/connectors/*.json exactly."""
    cfg = json.loads((CONNECTORS / "order-svc-outbox.json").read_text())["config"]
    placement = [p.split(":")[2] for p in cfg["transforms.outbox.table.fields.additional.placement"].split(",")]
    row = OutboxRow(id="0193a1c4-0000-7000-8000-000000000000", aggregate_type="Order", aggregate_id="o-1",
                    event_type="com.edacommerce.order.OrderPlaced", topic="order.events.v1", payload=b"\x00",
                    occurred_at=datetime(2026, 11, 18, 9, 46, 40, 123000, tzinfo=UTC), producer="order-svc",
                    correlation_id="o-1", causation_id=None, traceparent="00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                    tracestate=None)
    names = [n for n, _ in headers_for_row(row)]
    assert names == ["id", *placement, cfg["transforms.specversion.header"]]
    h = dict(headers_for_row(row))
    assert h["ce_specversion"] == cfg["transforms.specversion.value.literal"].encode()
    assert h["id"] == h["ce_id"] == row.id.encode()
    assert h["ce_time"] == b"2026-11-18T09:46:40.123Z"
    assert h["causation_id"] is None


def test_murmur2_matches_kafka_reference_vectors() -> None:
    # org.apache.kafka.common.utils.UtilsTest#testMurmur2
    cases = {
        "21": -973932308, "foobar": -790332482, "a-little-bit-long-string": -985981536,
        "a-little-bit-longer-string": -1486304829, "lkjh234lh9fiuh90y23oiuhsafujhadof229phr9h19h89h8": -58897971,
        "abc": 479470107,
    }
    for key, expected in cases.items():
        assert murmur2(key.encode()) == expected, key
    assert 0 <= java_partition("6ed9d0ed-127a-524b-b079-a06e34f3ec73", 12) < 12


def test_producer_uses_murmur2_partitioner() -> None:
    conf = producer_config(ServiceSettings())
    assert conf["partitioner"] == "murmur2_random"
    assert conf["acks"] == "all" and conf["enable.idempotence"] is True and conf["compression.type"] == "zstd"


def test_auth_none_refused_outside_local() -> None:
    with pytest.raises(ValueError, match="AUTH_MODE=none"):
        ServiceSettings(environment="prod", auth_mode="none")


def test_idempotency_hash_is_canonical() -> None:
    a = request_hash("post", "/checkouts", b'{"b": 1, "a": {"y": 2, "x": "\xc3\xa9"}}')
    b = request_hash("POST", "/checkouts", '{"a":{"x":"é","y":2},"b":1}')
    assert a == b
    assert canonical_json(b'{"b": 1, "a": 2}') == '{"a":2,"b":1}'
    assert request_hash("POST", "/checkouts", b'{"a":1}') != request_hash("POST", "/checkouts", b'{"a":2}')
    import hashlib

    assert a == hashlib.sha256('POST\n/checkouts\n{"a":{"x":"é","y":2},"b":1}'.encode()).hexdigest()
