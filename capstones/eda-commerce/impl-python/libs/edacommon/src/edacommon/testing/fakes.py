"""In-memory fakes for unit and integration tests."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from confluent_kafka.schema_registry import Schema
from confluent_kafka.schema_registry._sync.mock_schema_registry_client import MockSchemaRegistryClient
from confluent_kafka.schema_registry.error import SchemaRegistryError

import contracts_py
from contracts_py.topics import TOPICS
from edacommon.metrics import EdaMetrics, views


def _canonical(schema_str: str) -> str:
    """What normalize.schemas=true achieves on the real registry: whitespace and key order do not matter."""
    return json.dumps(json.loads(schema_str), sort_keys=True, separators=(",", ":"))


class InMemorySchemaRegistry(MockSchemaRegistryClient):  # type: ignore[misc]
    """confluent-kafka's mock registry, with lookups by normalised schema like the real registry."""

    def __init__(self) -> None:
        super().__init__({"url": "mock://eda"})
        self._ids: dict[tuple[str, str], Any] = {}
        self.available = True

    def register_schema_full_response(self, subject_name: str, schema: Schema, normalize_schemas: bool = False,
                                      **kw: Any) -> Any:
        rs = super().register_schema_full_response(subject_name, schema, normalize_schemas=False, **kw)
        self._ids[(subject_name, _canonical(schema.schema_str))] = rs
        return rs

    def lookup_schema(self, subject_name: str, schema: Schema, normalize_schemas: bool = False,
                      fmt: str | None = None, deleted: bool = False) -> Any:
        if not self.available:
            raise ConnectionError("schema registry down (test)")
        rs = self._ids.get((subject_name, _canonical(schema.schema_str)))
        if rs is None:
            raise SchemaRegistryError(404, 40403, "Schema not found")
        return rs

    def get_schema(self, schema_id: int, *a: Any, **kw: Any) -> Any:
        if not self.available:
            raise ConnectionError("schema registry down (test)")
        return super().get_schema(schema_id, *a, **kw)

    def register_all(self) -> InMemorySchemaRegistry:
        """Register every message under its TopicRecordNameStrategy subject (what `make schemas` does)."""
        for t in TOPICS:
            for full in t.messages:
                self.register_schema(f"{t.name}-{full}", Schema(contracts_py.schema_str(full), "AVRO"))
        return self


@dataclass
class ProducedRecord:
    topic: str
    key: bytes | None
    value: bytes | None
    headers: list[tuple[str, bytes | None]]

    @property
    def header_map(self) -> dict[str, str | None]:
        return {k: (None if v is None else v.decode()) for k, v in self.headers}


@dataclass
class FakeProducer:
    """Records produced messages; ``fail_next`` makes the next N deliveries fail."""

    records: list[ProducedRecord] = field(default_factory=list)
    fail_next: int = 0
    _pending: list[tuple[ProducedRecord, Callable[..., None] | None]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def produce(self, topic: str, value: bytes | None = None, key: bytes | None = None, headers: Any = None,
                on_delivery: Callable[..., None] | None = None, **_: Any) -> None:
        with self._lock:
            self._pending.append((ProducedRecord(topic, key, value, list(headers or [])), on_delivery))

    def poll(self, timeout: float = 0) -> int:
        return 0

    def flush(self, timeout: float = 0) -> int:
        with self._lock:
            pending, self._pending = self._pending, []
            for rec, cb in pending:
                if self.fail_next > 0:
                    self.fail_next -= 1
                    if cb:
                        cb("simulated delivery failure", None)
                    continue
                self.records.append(rec)
                if cb:
                    cb(None, rec)
        return 0

    def on(self, topic: str) -> list[ProducedRecord]:
        return [r for r in self.records if r.topic == topic]


def metrics_for_test() -> tuple[EdaMetrics, Any]:
    """EdaMetrics wired to an in-memory reader with the contract's bucket views."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader

    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader], views=views())
    return EdaMetrics(provider), reader


def collect(reader: Any) -> dict[str, list[Any]]:
    """name -> list of data points from an InMemoryMetricReader."""
    data = reader.get_metrics_data()
    out: dict[str, list[Any]] = {}
    if data is None:
        return out
    for rm in data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                out.setdefault(m.name, []).extend(m.data.data_points)
                out.setdefault(f"{m.name}#unit", []).append(m.unit)
    return out


def counter_value(reader: Any, name: str, **attrs: str) -> float:
    total = 0.0
    for p in collect(reader).get(name, []):
        if all(p.attributes.get(k) == v for k, v in attrs.items()):
            total += p.value
    return total
