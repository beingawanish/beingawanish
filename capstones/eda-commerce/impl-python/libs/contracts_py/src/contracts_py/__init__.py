"""Contracts for the Python build, generated from ``contracts/`` at build time.

Public surface:

* :mod:`contracts_py.records` - typed dataclasses / enums for every Avro record (generated)
* :mod:`contracts_py.topics`  - topic catalogue and retry policy (generated)
* :func:`schema_str`          - the bundled schema JSON for a record full name (package data)
* :func:`schema_dict`, :data:`SCHEMA_NAMES`
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

try:
    from contracts_py._generated import records as records
    from contracts_py._generated import topics as topics
except ImportError as exc:  # pragma: no cover - only when the build step was skipped
    raise ImportError(
        "contracts_py has not been generated. Run `uv sync` (the build hook generates it) or "
        "`uv run python libs/contracts_py/contracts_codegen.py`."
    ) from exc

_SCHEMAS = resources.files("contracts_py._generated.schemas")

SCHEMA_NAMES: tuple[str, ...] = tuple(
    sorted(p.name.removesuffix(".avsc") for p in _SCHEMAS.iterdir() if p.name.endswith(".avsc"))
)


@cache
def schema_str(full_name: str) -> str:
    """The bundled schema text exactly as in contracts/avro-bundled (used for SR lookups)."""
    return (_SCHEMAS / f"{full_name}.avsc").read_text(encoding="utf-8")


@cache
def _schema_dict(full_name: str) -> str:
    return schema_str(full_name)


def schema_dict(full_name: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(_schema_dict(full_name))
    return parsed


__all__ = ["SCHEMA_NAMES", "records", "schema_dict", "schema_str", "topics"]
