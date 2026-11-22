"""Workspace-wide pytest fixtures (shared by libs and every service)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from edacommon.ids import ManualClock
from edacommon.testing import FakeProducer, InMemorySchemaRegistry, metrics_for_test
from edacommon.testing.infra import fresh_database, kafka_bootstrap


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def schema_registry() -> InMemorySchemaRegistry:
    return InMemorySchemaRegistry().register_all()


@pytest.fixture
def fake_producer() -> FakeProducer:
    return FakeProducer()


@pytest.fixture
def metrics_reader():  # type: ignore[no-untyped-def]
    return metrics_for_test()


@pytest.fixture
def pg_url() -> Iterator[str]:
    """A fresh, empty database per test (EDA_TEST_PG_DSN, Testcontainers, or skip)."""
    with fresh_database() as url:
        yield url


@pytest.fixture(scope="session")
def kafka() -> str:
    return kafka_bootstrap()
