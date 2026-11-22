"""Avro serialisation in the Confluent wire format (guide §4 ``serde``, ADR-0004, §5 rules 3-6).

* ``TopicRecordNameStrategy``: subject = ``<topic>-<record full name>``.
* ``auto.register.schemas=false``, ``use.latest.version=false``, ``normalize.schemas=true``: the
  registry is the gate; only ``make schemas`` registers. A schema missing from the registry is a
  deployment error, not something a service silently fixes.
* Schema ids are cached by the confluent client, so a running service keeps working while the
  registry is down (chaos-registry drill).
* Deserialise with the **reader** schema of the handler, which gives schema resolution (new optional
  fields ignored, unknown enum symbols become ``UNKNOWN``).

Errors are classified here, once: registry unreachable -> :class:`Transient`; schema or id not found,
or bytes that do not decode -> :class:`NonRetryable`.
"""

from __future__ import annotations

import io
import json
import struct
import threading
from functools import cache
from typing import Any

import fastavro
from confluent_kafka.schema_registry import (
    Schema,
    SchemaRegistryClient,
    topic_record_subject_name_strategy,
)
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.schema_registry.error import SchemaRegistryError
from confluent_kafka.serialization import MessageField, SerializationContext, SerializationError

import contracts_py
from edacommon.errors import NonRetryable, Transient

MAGIC_BYTE = 0
SERIALIZER_CONF: dict[str, Any] = {
    "auto.register.schemas": False,
    "use.latest.version": False,
    "normalize.schemas": True,
    "subject.name.strategy": topic_record_subject_name_strategy,
}


def subject_for(topic: str, record_type: str) -> str:
    return f"{topic}-{record_type}"


def split_wire(data: bytes) -> tuple[int, bytes]:
    if len(data) < 5 or data[0] != MAGIC_BYTE:
        raise NonRetryable("value is not in the Confluent wire format (magic byte 0 + 4-byte id)")
    (schema_id,) = struct.unpack(">I", data[1:5])
    return schema_id, data[5:]


def join_wire(schema_id: int, avro_payload: bytes) -> bytes:
    return bytes([MAGIC_BYTE]) + struct.pack(">I", schema_id) + avro_payload


@cache
def parsed_schema(record_type: str) -> Any:
    return fastavro.parse_schema(json.loads(contracts_py.schema_str(record_type)))


def encode_raw(record_type: str, value: dict[str, Any]) -> bytes:
    """Schemaless Avro binary (no wire header). Used by golden tests and validation."""
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, parsed_schema(record_type), value)
    return buf.getvalue()


def decode_raw(record_type: str, data: bytes, writer_type: str | None = None) -> dict[str, Any]:
    writer = parsed_schema(writer_type or record_type)
    reader = parsed_schema(record_type)
    out: dict[str, Any] = fastavro.schemaless_reader(io.BytesIO(data), writer, reader)
    return out


def validate(record_type: str, value: dict[str, Any]) -> None:
    """Raise NonRetryable if ``value`` does not conform to the bundled schema."""
    from fastavro.validation import ValidationError, validate as fa_validate

    try:
        fa_validate(value, parsed_schema(record_type), raise_errors=True)
    except ValidationError as exc:
        raise NonRetryable(f"{record_type} does not match its schema: {exc}") from exc


def make_registry_client(url: str) -> SchemaRegistryClient:
    return SchemaRegistryClient({"url": url, "timeout": 5, "cache.capacity": 1000})


class AvroSerde:
    """Serialise and deserialise contract records through Schema Registry. Thread-safe."""

    def __init__(self, client: SchemaRegistryClient) -> None:
        self._client = client
        self._lock = threading.Lock()
        self._serializers: dict[str, AvroSerializer] = {}
        self._deserializers: dict[str, AvroDeserializer] = {}

    @property
    def client(self) -> SchemaRegistryClient:
        return self._client

    def _serializer(self, record_type: str) -> AvroSerializer:
        with self._lock:
            ser = self._serializers.get(record_type)
            if ser is None:
                ser = AvroSerializer(self._client, contracts_py.schema_str(record_type), conf=SERIALIZER_CONF)
                self._serializers[record_type] = ser
            return ser

    def _deserializer(self, reader_type: str) -> AvroDeserializer:
        with self._lock:
            de = self._deserializers.get(reader_type)
            if de is None:
                de = AvroDeserializer(self._client, contracts_py.schema_str(reader_type))
                self._deserializers[reader_type] = de
            return de

    def serialize(self, topic: str, record_type: str, value: dict[str, Any]) -> bytes:
        try:
            data = self._serializer(record_type)(value, SerializationContext(topic, MessageField.VALUE))
        except SchemaRegistryError as exc:
            raise _classify_sr(exc, f"{subject_for(topic, record_type)}") from exc
        except SerializationError as exc:
            cause = exc.__cause__ or exc
            if isinstance(cause, SchemaRegistryError):
                raise _classify_sr(cause, subject_for(topic, record_type)) from exc
            raise NonRetryable(f"cannot serialise {record_type}: {exc}") from exc
        except (ConnectionError, OSError) as exc:
            raise Transient(f"schema registry unreachable: {exc}") from exc
        except Exception as exc:
            if _is_http_error(exc):
                raise Transient(f"schema registry unreachable: {exc}") from exc
            raise NonRetryable(f"cannot serialise {record_type}: {exc}") from exc
        assert data is not None
        return bytes(data)

    def deserialize(self, topic: str, reader_type: str, data: bytes) -> dict[str, Any]:
        split_wire(data)  # fail fast and clearly on raw Avro or garbage
        try:
            value = self._deserializer(reader_type)(data, SerializationContext(topic, MessageField.VALUE))
        except SchemaRegistryError as exc:
            raise _classify_sr(exc, f"schema id of a {reader_type} on {topic}") from exc
        except (ConnectionError, OSError) as exc:
            raise Transient(f"schema registry unreachable: {exc}") from exc
        except Exception as exc:
            if _is_http_error(exc):
                raise Transient(f"schema registry unreachable: {exc}") from exc
            raise NonRetryable(f"cannot deserialise {reader_type} from {topic}: {exc}") from exc
        if not isinstance(value, dict):
            raise NonRetryable(f"{reader_type} decoded to {type(value).__name__}")
        return value

    def schema_id(self, topic: str, record_type: str) -> int:
        """Look up (and cache) the registered id; used to warm the cache for readiness."""
        try:
            reg = self._client.lookup_schema(
                subject_for(topic, record_type), Schema(contracts_py.schema_str(record_type), "AVRO"),
                normalize_schemas=True,
            )
        except SchemaRegistryError as exc:
            raise _classify_sr(exc, subject_for(topic, record_type)) from exc
        except Exception as exc:
            raise Transient(f"schema registry unreachable: {exc}") from exc
        return int(reg.schema_id)

    def warm(self, pairs: list[tuple[str, str]]) -> None:
        for topic, record_type in pairs:
            self.schema_id(topic, record_type)


def _is_http_error(exc: BaseException) -> bool:
    mod = type(exc).__module__
    return mod.startswith(("httpx", "httpcore", "requests", "urllib3"))


def _classify_sr(exc: SchemaRegistryError, what: str) -> Exception:
    status = getattr(exc, "http_status_code", None)
    if status in (404, 422, 409):
        return NonRetryable(f"schema not registered for {what} (run `make schemas`): {exc}")
    if status is None or status >= 500 or status == -1:
        return Transient(f"schema registry error for {what}: {exc}")
    return NonRetryable(f"schema registry refused {what}: {exc}")
