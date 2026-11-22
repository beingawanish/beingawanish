"""Real infrastructure for integration tests (ADR-0014 layer 3).

Order of preference, so the same tests run in CI with Docker and on machines without it:

1. ``EDA_TEST_PG_DSN`` / ``EDA_TEST_KAFKA_BOOTSTRAP``: an externally started Postgres / Kafka
   (e.g. ``make up`` or a CI service container);
2. Testcontainers (``postgres:16``, ``apache/kafka``) when a Docker daemon is reachable;
3. otherwise ``pytest.skip`` with a clear reason (never a fake pass).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def docker_available() -> bool:
    try:
        import docker

        docker.from_env(timeout=3).ping()
        return True
    except Exception:
        return False


_pg_container: Any = None
_kafka_container: Any = None


def admin_postgres_url() -> str:
    global _pg_container
    dsn = os.environ.get("EDA_TEST_PG_DSN")
    if dsn:
        return dsn
    if _pg_container is None:
        if not docker_available():
            pytest.skip("integration: set EDA_TEST_PG_DSN or provide a Docker daemon for Testcontainers")
        from testcontainers.postgres import PostgresContainer

        _pg_container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        _pg_container.with_command("postgres -c wal_level=logical")
        _pg_container.start()
    return str(_pg_container.get_connection_url())


@contextmanager
def fresh_database(prefix: str = "eda") -> Iterator[str]:
    """Create an empty database for one test module and drop it afterwards."""
    admin = make_url(admin_postgres_url()).set(drivername="postgresql+psycopg")
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    eng = create_engine(admin, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield admin.set(database=name).render_as_string(hide_password=False)
    finally:
        with eng.connect() as c:
            c.execute(text(f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{name}'"))
            c.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        eng.dispose()


def kafka_bootstrap() -> str:
    global _kafka_container
    bs = os.environ.get("EDA_TEST_KAFKA_BOOTSTRAP")
    if bs:
        return bs
    if _kafka_container is None:
        if not docker_available():
            pytest.skip("kafka: set EDA_TEST_KAFKA_BOOTSTRAP or provide a Docker daemon for Testcontainers")
        from testcontainers.kafka import KafkaContainer

        _kafka_container = KafkaContainer("confluentinc/cp-kafka:7.9.0").with_kraft()
        _kafka_container.start()
    return str(_kafka_container.get_bootstrap_server())


def create_topics(bootstrap: str, names: list[str], partitions: int = 1) -> None:
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap})
    existing = set(admin.list_topics(timeout=10).topics)
    new = [NewTopic(n, num_partitions=partitions, replication_factor=1) for n in names if n not in existing]
    if new:
        for f in admin.create_topics(new).values():
            try:
                f.result(timeout=20)
            except Exception as exc:  # already exists after a race
                if "TOPIC_ALREADY_EXISTS" not in str(exc):
                    raise


def migrate(url: str, script_location: Path) -> None:
    from edacommon.migrations.runner import migrate as run

    run(script_location, url)


def information_schema_columns(url: str, tables: list[str]) -> list[tuple[Any, ...]]:
    eng = create_engine(url)
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT table_name, column_name, ordinal_position, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ANY(:t) "
            "ORDER BY table_name, ordinal_position"), {"t": tables}).all()
    eng.dispose()
    return [tuple(r) for r in rows]


def contract_sql_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "contracts" / "sql" / "common-tables.sql"
        if cand.exists():
            return cand
    raise FileNotFoundError("contracts/sql/common-tables.sql not found above " + str(here))
