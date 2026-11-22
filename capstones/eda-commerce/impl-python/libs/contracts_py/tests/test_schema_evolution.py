"""Reader-schema resolution: unknown enum symbols become UNKNOWN (guide §5 rule 9), and new optional
fields from a newer writer are ignored by an old reader (FULL_TRANSITIVE in practice)."""

from __future__ import annotations

import io
import json
from typing import Any

import contracts_py
import fastavro
from contracts_py.records import DeclineReason, PaymentDeclined, ShippingMethod
from edacommon.serde import parsed_schema


def _newer_writer(name: str, mutate: Any) -> Any:
    schema = json.loads(contracts_py.schema_str(name))
    mutate(schema)
    return fastavro.parse_schema(schema)


def _write(schema: Any, value: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, value)
    return buf.getvalue()


def _example(name: str) -> dict[str, Any]:
    from pathlib import Path

    p = Path(__file__).resolve().parents[4] / "contracts" / "examples" / f"{name}.json"
    return json.loads(p.read_text())


def test_unknown_enum_symbol_decodes_to_unknown() -> None:
    name = "com.edacommerce.payment.PaymentDeclined"

    def add_symbol(s: dict[str, Any]) -> None:
        for f in s["fields"]:
            if f["name"] == "reason":
                f["type"]["symbols"].insert(0, "BANK_OFFLINE")

    writer = _newer_writer(name, add_symbol)
    value = _example(name)
    value["reason"] = "BANK_OFFLINE"
    data = _write(writer, value)
    decoded = fastavro.schemaless_reader(io.BytesIO(data), writer, parsed_schema(name))
    assert decoded["reason"] == "UNKNOWN"
    rec = PaymentDeclined.from_avro(decoded)
    assert rec.reason is DeclineReason.UNKNOWN


def test_enum_parse_is_total() -> None:
    assert ShippingMethod.parse("DRONE") is ShippingMethod.UNKNOWN
    assert ShippingMethod.parse("EXPRESS") is ShippingMethod.EXPRESS


def test_new_optional_field_is_ignored_by_old_reader() -> None:
    name = "com.edacommerce.order.OrderConfirmed"

    def add_field(s: dict[str, Any]) -> None:
        s["fields"].append({"name": "loyaltyPoints", "type": ["null", "int"], "default": None})

    writer = _newer_writer(name, add_field)
    value = _example(name)
    value["loyaltyPoints"] = 42
    decoded = fastavro.schemaless_reader(io.BytesIO(_write(writer, value)), writer, parsed_schema(name))
    assert "loyaltyPoints" not in decoded
    assert decoded["orderId"] == value["orderId"]
