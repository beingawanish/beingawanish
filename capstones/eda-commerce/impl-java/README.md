# eda-commerce, Java build

This is the Java implementation of the eda-commerce design in `../docs/` and `../contracts/`. It is meant to be forked as a template, so the shared library is complete and every service follows one layout.

Wave 1 contains the shared library and five services: catalog-svc, checkout-svc, order-svc (the order saga orchestrator and the order-history projector), inventory-svc and payment-svc (with the fake PSP). Wave 2 adds fulfilment-svc, shipping-svc, notification-svc and returns-svc using the same pattern (see "Adding a service").

## Layout

```
impl-java/
├── settings.gradle.kts          multi-project; includes build-logic (convention plugins)
├── gradle/libs.versions.toml    every dependency version, pinned
├── build-logic/                 eda.java-conventions (Java 21, BOMs, Error Prone, Spotless, JUnit 5)
│                                eda.spring-service   (Spring Boot service; copies migration V1 from contracts/sql)
├── libs/contracts-java/         Avro SpecificRecord classes generated from ../contracts/avro-bundled (never committed)
├── libs/kernel/                 shared kernel: Money (integer minor units, banker's rounding)
├── libs/edacommon/              the shared library of guide §4 (+ testFixtures used by every service's tests)
└── services/<name>-svc/         one Spring Boot service per bounded context, hexagonal layout
```

Each service has `domain/` (pure Java), `application/` (use cases and ports), `adapters/in|out/...` (HTTP, messaging, persistence, fakes) and `config/` (composition root), checked by an ArchUnit test (`HexagonalArchitecture.check`). The domain may import only the JDK and `libs/kernel`.

## Build and test

Requirements: Java 21 and network access to Maven Central and the Gradle plugin portal. Gradle 8.14 is pinned by the wrapper.

```bash
./gradlew build                 # compile (with Error Prone), Spotless check, all tests, boot jars
./gradlew spotlessApply         # format (google-java-format)
./gradlew :services:order-svc:test --tests '*OrderSagaTest*'
```

Tests come in three kinds, following ADR-0014:

| Kind | Where | Needs |
|---|---|---|
| Domain unit tests and jqwik property tests | `src/test/.../unit` | nothing |
| Contract tests: golden `.bin` round trips, produced messages validated against the bundled schemas | `src/test/.../contract`, `libs/edacommon/.../contracts/GoldenFixturesTest` | nothing |
| Integration tests: the real Spring context and Flyway on PostgreSQL 16, handlers driven through the real consumer runtime (`MessageDriver`), HTTP through MockMvc with OpenAPI response validation | `src/test/.../integration`, `libs/edacommon/.../it` | PostgreSQL (see below) |
| Broker tests: Kafka retry/DLQ/replay/shutdown, Debezium connector | `libs/edacommon/.../it/ConsumerRuntimeKafkaIT`, `DebeziumOutboxIT` | Docker |

PostgreSQL for integration tests comes from Testcontainers (`postgres:16-alpine`) when Docker is available. Without Docker, set `EDA_TEST_JDBC_URL` to an admin connection (for example `jdbc:postgresql://127.0.0.1:5432/postgres`, plus `EDA_TEST_JDBC_USER` / `EDA_TEST_JDBC_PASSWORD`); each test context gets its own fresh database. With neither, those tests are skipped, not failed. The Kafka and Debezium tests use `@Testcontainers(disabledWithoutDocker = true)`.

## Run

Bring up the shared infrastructure from the repository root (`make up topics schemas`), then run services on the host:

```bash
./gradlew :services:inventory-svc:bootJar
SERVICE_NAME=inventory-svc java -jar services/inventory-svc/build/libs/inventory-svc.jar
OUTBOX_RELAY=polling ...                          # without Kafka Connect
java -jar services/order-svc/build/libs/order-svc.jar projector   # the order-history projector
```

All configuration is the environment variables of guide §7 (`infra/compose.apps.example.yml`). `EdaEnvironmentPostProcessor` maps them onto Spring properties in one place, with the documented defaults (`<context>_db`, `<context>_svc`, port 8101–8105, 2 s pool timeout). `AUTH_MODE=none` is refused unless `ENVIRONMENT=local`; with it, `X-Local-Customer-Id` may name the caller (default `local-customer`). Logs are JSON (`ts`, `level`, `service`, `impl`, `msg`, `trace_id`, `span_id`, `correlation_id`, `event_id`, `event_type`, `order_id`, `error.*`); `LOG_FORMAT=plain` switches to text.

## How the code maps to the design

| Design | Code |
|---|---|
| Outbox (ADR-0003) | `edacommon.outbox.OutboxWriter` (in the caller's transaction, wire-format payload, trace context from the current span); `PollingOutboxRelay` (`OUTBOX_RELAY=polling`, headers identical to the Debezium router, `FOR UPDATE SKIP LOCKED`); `Housekeeping` |
| Serde (ADR-0004) | `edacommon.serde.AvroSerde` + `HttpSchemaRegistryClient`: Confluent wire format, TopicRecordNameStrategy, lookup with `normalize=true`, no auto-registration, reader-schema resolution with the generated class |
| Consumer runtime (guide §4.1, ADR-0006/0007) | `RecordProcessor` (dispatch on `ce_type` before deserialising, inbox + handler in one transaction, consumer span, metrics); `ConsumerContainers` (Spring Kafka, `MANUAL_IMMEDIATE`, `DefaultErrorHandler` retrying only `TransientException` 5× with jitter, stop after the in-flight record); `FailureForwarder` (a `DeadLetterPublishingRecoverer` writing raw bytes to `G.retry.10s/1m/10m` and `G.dlq` with the `x-*` headers); the retry container (group `G-retry`) waits for `x-not-before`; `DlqService`/`DlqController` (`/ops/dlq`, `/ops/dlq/replay`) |
| Saga kit (ADR-0008) | `SagaEngine` (lock row, decide, outbox, version+1, transition row, metrics after commit), `SagaRepository`, `DeadlineSweeper` (`SKIP LOCKED`, one transaction per saga, `eda.saga.overdue`), `SagaOpsController` |
| Idempotency keys (ADR-0012) | `IdempotencyFilter`: SHA-256 of method, path, canonical JSON; the key row, an advisory lock and the business change share one transaction (replay, 409, 422) |
| Claim check (ADR-0009) | `ClaimCheckStore`, `S3ClaimCheckStore` (AWS SDK v2, path style), `ClaimChecks.key` |
| Webhooks (ADR-0013) | `WebhookVerifier` (HMAC over `"<ts>.<body>"`, 300 s, constant time), `WebhookReceiver` (inbox dedupe, store then ack) |
| Observability (ADR-0011, guide §8) | `EdaMetrics` (every instrument with the contract's names, units, attributes and bucket advice), `MessagingTracing` (W3C only, consumer span with parent + link), `logback-spring.xml`, `PiiRedactor` |
| HTTP (guide §6) | `ProblemHandler` (RFC 9457, `https://errors.edacommerce.example/…`, 503 + Retry-After for transient failures), `HealthController` (`/health/live`, `/health/ready`), `SecurityConfiguration` |
| Order saga (architecture §5) | `services/order-svc/.../domain/OrderSaga.java`: a pure transition function over the state table, with early events recorded in `data.pending` |

## Adding a service (wave 2 pattern)

1. Copy `services/inventory-svc` (a participant) or `services/order-svc` (an orchestrator), rename the package `com.edacommerce.<context>` and add it to `settings.gradle.kts`.
2. `build.gradle.kts`: `plugins { id("eda.spring-service") }`. Migration V1 (the shared tables) is copied from `contracts/sql` by the build; put private tables in `V2__<context>.sql`.
3. `application.yml`: `eda.service-name`, `server.port`, `eda.consumer.topics`, service-specific `${ENV:default}` settings.
4. Domain first (pure, unit-tested), then use cases with ports, then adapters. Message handlers are `MessageHandler<T>` beans (or one `MessageHandlerGroup`); they call one use case each and translate domain errors to `NonRetryableException`.
5. Tests: copy `ArchitectureTest`, a contract test listing the consumed golden messages and validating produced ones, and an `@EdaServiceTest` integration test with `MessageDriver` and `SharedTables.assertMatchesContract`.

## Deviations and decisions specific to this build

- **Confluent serializer not used.** `packages.confluent.io` was not reachable from the build environment, so `kafka-avro-serializer` could not be resolved. `AvroSerde` implements the same wire format and registry semantics (`auto.register.schemas=false`, `normalize.schemas=true`, TopicRecordNameStrategy, schema-id cache, reader-schema resolution) on the registry's REST API. Swapping in `KafkaAvroSerializer` is local to `edacommon.serde`.
- **Persistence.** inventory-svc, payment-svc and order-svc map their aggregates with Spring Data JPA; hot-path conditional updates (stock), shared tables (outbox, inbox, saga, idempotency) and the version-guarded projections (catalog view, order history, stock levels) use `JdbcTemplate` in the same transaction, because those statements are clearer as SQL.
- **PSP calls inside the consumer transaction.** They are idempotent on paymentId/refundId and bounded by the 5 s timeout; see `services/payment-svc/README.md`.
- **Unspecified details, aligned with the Python build:** `x-*` timestamps are RFC 3339 UTC with milliseconds (`2026-11-22T09:15:00.123Z`); null header values (Debezium's for a null `causation_id`/`tracestate`) are tolerated and reproduced by the polling relay; CheckoutSubmitted's `aggregateId` is the checkoutId; a transition emitting n order events advances the order's `aggregateVersion` by n; the empty request body canonicalises to the empty string for the idempotency hash.
