from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from edacommon.config import ServiceSettings
from edacommon.db import Database
from edacommon.migrations.common_tables import statements
from edacommon.serde import AvroSerde, decode_raw
from sqlalchemy import create_engine, text

EXAMPLES = Path(__file__).resolve().parents[4] / "contracts" / "examples"


def example(name: str) -> dict[str, Any]:
    """Golden example decoded as fastavro would (datetimes for timestamps)."""
    return decode_raw(name, (EXAMPLES / f"{name}.bin").read_bytes())


def example_json(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / f"{name}.json").read_text())


@pytest.fixture
def db(pg_url: str) -> Iterator[Database]:
    eng = create_engine(pg_url)
    with eng.begin() as c:
        for stmt in statements(saga=True):
            c.execute(text(stmt))
        c.execute(text("CREATE TABLE effect (id text PRIMARY KEY, n int NOT NULL)"))
    eng.dispose()
    from edacommon.db import make_engine

    database = Database(make_engine(ServiceSettings(db_pool_size=5), url=pg_url))
    yield database
    database.dispose()


@pytest.fixture
def serde(schema_registry: Any) -> AvroSerde:
    return AvroSerde(schema_registry)
