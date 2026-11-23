"""Test support shared by every service: schema registry, producer and broker fakes, metric readers,
database and Kafka fixtures (Testcontainers, or ``EDA_TEST_*`` env vars), OpenAPI validation."""

from edacommon.testing.fakes import FakeProducer, InMemorySchemaRegistry, metrics_for_test

__all__ = ["FakeProducer", "InMemorySchemaRegistry", "metrics_for_test"]
