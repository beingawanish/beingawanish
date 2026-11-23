# edacommon (Java)

The shared library of implementation guide §4. Every service depends on it; it depends on no service. Spring Boot auto-configuration (`EdaCommonAutoConfiguration`) wires everything from the §7 environment variables, so a service only declares handlers, use cases and adapters.

| Package | What it gives a service |
|---|---|
| `config` | `EdaProperties`, `EdaEnvironmentPostProcessor` (env var -> property mapping and defaults) |
| `ids` | UUIDv7 (`Ids`, `IdGenerator`) |
| `envelope` | `OutgoingMessage`, `MessageContext`, `Causation`, `Envelopes`, header names |
| `serde` | `AvroSerde`, `HttpSchemaRegistryClient` |
| `outbox` / `inbox` | `OutboxWriter`, `PollingOutboxRelay`, `Housekeeping`, `Inbox` |
| `consumer` | `MessageHandler`, `MessageHandlerGroup`, `RecordProcessor`, `ConsumerContainers`, `FailureForwarder`, `RetryTopics`, `DlqService`, `DlqController` |
| `saga` | `SagaEngine`, `SagaRepository`, `DeadlineSweeper`, `SagaOperator`, `SagaOpsController` |
| `idempotency` | `IdempotencyFilter`, `CanonicalJson`, `IdempotencyStore` |
| `claimcheck` | `ClaimCheckStore`, `S3ClaimCheckStore`, `ClaimChecks` |
| `webhooks` | `WebhookVerifier`, `WebhookReceiver` |
| `tracing` / `metrics` / `logging` | `MessagingTracing`, `EdaMetrics`, `logback-spring.xml`, `PiiRedactor`, `LogFields` |
| `http` | `ApiProblem`, `ProblemHandler`, `HealthController`, `Caller`, `SecurityConfiguration` |
| `jobs` | `PeriodicJob` (relay, sweepers, reconciliation) |
| `errors` | `TransientException`, `RetryLaterException`, `NonRetryableException`, `ErrorClassifier` |

`src/testFixtures` is the test kit services use: `@EdaServiceTest`, `MessageDriver`, `TestDatabases`, `InMemorySchemaRegistry`, `InMemoryClaimCheckStore`, `MutableClock`, `GoldenFixtures`, `OpenApiContract`, `SharedTables`, `HexagonalArchitecture`, `TestTelemetry`.

## Decisions and trade-offs

- **Dispatch before deserialising, raw bytes everywhere.** Values stay `byte[]` until a handler is found by `ce_type`; forwarding to retry/DLQ copies the bytes and never re-serialises (ADR-0005, ADR-0007). Cost: handlers cannot use Spring's `@KafkaListener` payload conversion.
- **Spring's `DefaultErrorHandler` + `DeadLetterPublishingRecoverer`, our topic names.** In-place retry is only for `TransientException` (5 attempts, 200 ms to 3.2 s, jitter); everything else goes to `G.retry.*` at once, unknown exceptions count as RetryLater (ADR-0007). The recoverer's own `kafka_dlt-*` headers are replaced by the `x-*` headers both builds share.
- **`MANUAL_IMMEDIATE` acks.** One synchronous commit per record after the DB commit, as the guide requires; the batched "every 1 s or 500 records" optimisation is not implemented (simpler, slightly more commit traffic).
- **The retry consumer waits with `nack(sleep)`.** The partition is paused and the consumer keeps polling, so membership survives 10-minute delays; head-of-line waiting is fine because each retry topic has a constant delay.
- **Idempotency: one transaction plus an advisory lock.** The key row is written in the business transaction (ADR-0012) and a `pg_try_advisory_xact_lock` gives concurrent duplicates an immediate 409 instead of queueing; non-2xx answers store nothing.
- **Metrics through the OpenTelemetry API with bucket advice.** No SDK views needed, identical boundaries to the Python build (ADR-0011).
