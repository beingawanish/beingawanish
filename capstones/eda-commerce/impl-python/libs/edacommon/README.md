# edacommon

The shared runtime of guide §4, written once and used by every Python service. The module map is in `src/edacommon/__init__.py`, and the top-level README maps modules to ADRs. Rules for changing it:

- Behaviour must match the Java build. Header names and order, envelope rules, retry topology, idempotency hashing, metric names and buckets are all contract-level.
- Every module has tests in `tests/`: pure ones, Postgres-backed ones (`integration`) and real-Kafka ones (`kafka`).
- It depends on no service (import-linter enforces this).

`edacommon.testing` ships the fixtures and fakes that services' tests use: `ServiceHarness`, `InMemorySchemaRegistry`, `FakeProducer`, `metrics_for_test`, OpenAPI response validation, and Testcontainers / `EDA_TEST_*` infrastructure discovery.
