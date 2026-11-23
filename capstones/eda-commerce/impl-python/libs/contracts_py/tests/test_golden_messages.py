"""Golden-message contract tests (ADR-0014 layer 2, checklist §11 "Contracts").

For every message in contracts/examples:

* the raw Avro ``.bin`` decodes (with the bundled schema) to exactly the ``.json`` values;
* decoding into the generated dataclass and back, then encoding, reproduces the ``.bin`` byte for byte;
* encoding the ``.json`` reproduces the ``.bin`` byte for byte;
* through the Schema Registry serde the value is the Confluent wire format: magic byte, 4-byte id,
  then exactly the golden bytes.

These run in milliseconds and are the cross-language interoperability guarantee.
"""

from __future__ import annotations

import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any

import contracts_py
import pytest
from contracts_py.records import MESSAGE_TYPES
from contracts_py.topics import MESSAGE_TOPIC
from edacommon.serde import AvroSerde, decode_raw, encode_raw, validate
from edacommon.testing import InMemorySchemaRegistry

EXAMPLES = Path(__file__).resolve().parents[4] / "contracts" / "examples"
NAMES = sorted(p.stem for p in EXAMPLES.glob("*.bin"))


def normalise(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: normalise(x) for k, x in v.items()}
    if isinstance(v, list):
        return [normalise(x) for x in v]
    if isinstance(v, datetime):
        return int(v.timestamp() * 1000)
    return v


def test_every_message_has_a_golden_example() -> None:
    assert set(NAMES) == set(MESSAGE_TYPES), "examples and generated message types differ"
    assert len(NAMES) == 54


@pytest.mark.parametrize("name", NAMES)
def test_bin_decodes_to_json(name: str) -> None:
    raw = (EXAMPLES / f"{name}.bin").read_bytes()
    expected = json.loads((EXAMPLES / f"{name}.json").read_text())
    assert normalise(decode_raw(name, raw)) == expected


@pytest.mark.parametrize("name", NAMES)
def test_typed_round_trip_is_byte_identical(name: str) -> None:
    raw = (EXAMPLES / f"{name}.bin").read_bytes()
    record = MESSAGE_TYPES[name].from_avro(decode_raw(name, raw))
    assert name == record.AVRO_NAME
    assert encode_raw(name, record.to_avro()) == raw


@pytest.mark.parametrize("name", NAMES)
def test_json_encodes_to_bin(name: str) -> None:
    raw = (EXAMPLES / f"{name}.bin").read_bytes()
    value = json.loads((EXAMPLES / f"{name}.json").read_text())
    validate(name, value)
    assert encode_raw(name, value) == raw
    # and via the typed record built from JSON (epoch-millis timestamps accepted)
    assert encode_raw(name, MESSAGE_TYPES[name].from_avro(value).to_avro()) == raw


@pytest.mark.parametrize("name", NAMES)
def test_wire_format_through_schema_registry(name: str) -> None:
    registry = InMemorySchemaRegistry().register_all()
    serde = AvroSerde(registry)
    topic = MESSAGE_TOPIC[name]
    raw = (EXAMPLES / f"{name}.bin").read_bytes()
    value = decode_raw(name, raw)
    wire = serde.serialize(topic, name, value)
    schema_id = serde.schema_id(topic, name)
    assert wire[0] == 0
    assert struct.unpack(">I", wire[1:5])[0] == schema_id
    assert wire[5:] == raw
    assert normalise(serde.deserialize(topic, name, wire)) == normalise(value)


def test_bundled_schemas_are_package_data_verbatim() -> None:
    bundled = EXAMPLES.parent / "avro-bundled"
    for name in contracts_py.SCHEMA_NAMES:
        assert contracts_py.schema_str(name) == (bundled / f"{name}.avsc").read_text()


def test_generated_tree_is_current() -> None:
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "contracts_codegen.py"
    spec = importlib.util.spec_from_file_location("contracts_codegen_check", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["contracts_codegen_check"] = mod
    spec.loader.exec_module(mod)
    assert mod.main(["--check"]) == 0
