# eda-commerce: Python build

This is the Python implementation of the design in `../docs/` and `../contracts/`. It is a template you can fork: a uv workspace with one shared runtime library (`edacommon`), a generated contracts package (`contracts_py`) and one hexagonal package per service.

**Wave 1:** `edacommon` (complete), `contracts_py`, catalog-svc, checkout-svc, order-svc (the order saga, plus the order-history projector), inventory-svc and payment-svc (with the fake PSP).
**Wave 2:** fulfilment-svc (fake WMS, packing manifests by claim check), shipping-svc (fake carrier, signed webhooks, label PDFs), notification-svc (choreographed emails with attachments) and returns-svc (the returns saga). All nine services of guide §2 are in this tree. order-svc needed no changes: its saga already covered dispatch, capture, shipping and delivery against the contracts.

## Layout

```
impl-python/
├── pyproject.toml            uv workspace root: pinned dev tools, pytest/ruff/mypy/import-linter config
├── uv.lock                   exact versions for every package
├── conftest.py               workspace fixtures (clock, schema registry, Postgres/Kafka)
├── Dockerfile                one image per service (build arg SERVICE)
├── libs/
│   ├── contracts_py/         codegen from ../contracts/avro-bundled + topics.yaml (output is not committed)
│   └── edacommon/            the shared runtime of guide §4
└── services/
    ├── catalog_svc/  checkout_svc/  order_svc/  inventory_svc/  payment_svc/
    ├── fulfilment_svc/  shipping_svc/  notification_svc/  returns_svc/
    └── <svc>/
        ├── pyproject.toml  alembic.ini  README.md
        ├── migrations/versions/0001_common_tables.py   contracts/sql/common-tables.sql, statement for statement
        ├── migrations/versions/0002_<svc>_tables.py    private tables as explicit SQL
        ├── src/<svc>/{domain,application,adapters}/    hexagonal layers (guide §3)
        ├── src/<svc>/config.py  main.py                env vars of guide §7; the composition root
        └── tests/{unit,integration}/
```

## Running it

Prerequisites: Python 3.13 and [uv](https://docs.astral.sh/uv/). For a full run you also need the infrastructure from `../infra` (`make up topics schemas` at the capstone root).

```bash
cd impl-python
uv sync                                   # installs everything; the contracts_py build hook generates its code
uv run inventory-svc                      # = serve: migrates its DB, then HTTP + consumers + workers
uv run inventory-svc migrate              # migrate only
uv run order-svc projector                # the order-history projector (its own process and group)
uv run returns-svc                        # likewise fulfilment-svc, shipping-svc, notification-svc
```

Every service reads only the environment variables of guide §7 (`SERVICE_NAME`, `HTTP_PORT`, `KAFKA_BOOTSTRAP_SERVERS`, `DB_*`, `OUTBOX_RELAY`, `SAGA_*`, `RESERVATION_*`, `PSP_*`, `FAKE_PSP_*`, `FAKE_WMS_*`, `CARRIER_WEBHOOK_*`, `FAKE_CARRIER_*`, `RETURN_*` ...). The defaults are the local host-run values, so on a machine running `make up` you can start the services with no configuration at all. Set `OUTBOX_RELAY=polling` if Kafka Connect is not running. Containers: `docker build --build-arg SERVICE=order_svc -t eda-commerce/order-svc-python:dev .`, then use `../infra/compose.apps.example.yml`.

When `contracts/` changes, rebuild the generated code. `uv sync` does it on its own, because the bundled schemas are `cache-keys` of the package. You can also run `uv run python libs/contracts_py/contracts_codegen.py`; `--check` is the CI gate.

## Testing

```bash
uv run pytest                              # everything; integration tests skip cleanly without infra
uv run pytest -m "not integration"         # pure tests only (milliseconds)
uv run ruff check . && uv run ruff format --check .
uv run mypy                                # --strict, all libs and services
uv run lint-imports                        # the dependency rule (guide §3)
```

Integration tests use real infrastructure, found in this order:

1. `EDA_TEST_PG_DSN` (an admin DSN; every test gets a fresh database) and `EDA_TEST_KAFKA_BOOTSTRAP`;
2. Testcontainers (`postgres:16-alpine`, `confluentinc/cp-kafka:7.9.0` in KRaft mode), when a Docker daemon is reachable;
3. otherwise `pytest.skip`, with the reason printed. A test without infrastructure never passes as a fake.

Schema Registry is replaced in tests by `edacommon.testing.InMemorySchemaRegistry`. It is confluent-kafka's mock client with normalised schema lookup, and every bundled schema is registered under its `TopicRecordNameStrategy` subject, exactly as `make schemas` does it. Object storage uses moto's S3 API.

### Results in the authoring environment

There was no Docker daemon. Postgres 16 and Apache Kafka 3.9.1 (KRaft) ran natively and were passed in through the `EDA_TEST_*` variables.

| Check | Result |
|---|---|
| `uv run pytest` with Postgres + Kafka | **531 passed** (wave 1: contracts 222, edacommon 51, catalog 8, checkout 10, order 52, inventory 30, payment 31; wave 2: fulfilment 37, shipping 44, notification 16, returns 30) |
| `uv run pytest` with no infrastructure | 411 passed, 120 skipped (every integration test, each with its reason) |
| `ruff check`, `ruff format --check` | clean |
| `mypy --strict` (260 source files) | clean |
| `lint-imports` | 6 contracts kept, 0 broken |
| Process smoke test (`inventory-svc serve` in wave 1, `returns-svc serve` in wave 2; real Kafka + Postgres, no registry) | live 200; ready 503 (schema cache cold, as designed); `POST /returns` for an unknown order returns a 404 problem; SIGTERM stops the sweeper, consumers and HTTP cleanly |

Not run here: a real Confluent Schema Registry (its download host was blocked), Debezium/Kafka Connect, MinIO, the OTel Collector, and the shared component suite (layer 4).

## How the code maps to the design

| Design element | Where |
|---|---|
| Consumer algorithm of guide §4.1 (dispatch on `ce_type` before deserialising, inbox, in-place retry, retry/DLQ forwarding, commit after DB) | `edacommon/consumer/processor.py`; poll loop, offsets, rebalance, shutdown in `consumer/loop.py` |
| Retry topics `<G>.retry.10s/1m/10m`, `<G>.dlq`, `x-*` headers, raw bytes unchanged (ADR-0007) | `edacommon/consumer/forwarder.py`; retry consumer = `ConsumerLoop(retry_mode=True)` honouring `x-not-before` |
| `GET /ops/dlq`, `POST /ops/dlq/replay` | `edacommon/consumer/dlq.py`, `edacommon/http.py:dlq_router` |
| Transactional outbox, Debezium-identical headers, polling relay with murmur2 (ADR-0003, guide §5.1) | `edacommon/outbox.py`, `envelope.py:headers_for_row`, `kafka.py` |
| Inbox (ADR-0006) | `edacommon/inbox.py` (`INSERT ... ON CONFLICT DO NOTHING`) |
| Envelope rules (type, partitionKey, causation, correlation, aggregateVersion) | `edacommon/envelope.py`, `outbox.py:OutboxWriter` |
| Avro + Schema Registry, TopicRecordNameStrategy, no auto-registration, normalised schemas (ADR-0004) | `edacommon/serde.py` |
| Saga kit: one transaction per transition, optimistic locking, transition log, sweeper with `SKIP LOCKED`, ops endpoints (ADR-0008) | `edacommon/saga/` |
| Order saga state machine (architecture §5) | `order_svc/domain/saga.py` (pure) and `application/handle_saga_trigger.py` |
| Returns saga, forward recovery (architecture §6) | `returns_svc/domain/saga.py` (pure), `domain/policy.py` (eligibility, refund rule), `application/returns.py` |
| Fulfilment ↔ shipping choreography (ADR-0001) | `fulfilment_svc` (OrderPacked → `shipping_svc` books → ShipmentCreated → OrderDispatched) |
| Fakes behind ports: WMS, carrier, mail | `fulfilment_svc/adapters/outbound/wms/fake/`, `shipping_svc/adapters/outbound/carrier/fake/`, `notification_svc/adapters/outbound/mail/fake/` |
| Carrier webhook normalisation (architecture §5.10) | `shipping_svc/domain/model.py:normalise`, `adapters/inbound/jobs/workers.py` |
| Idempotency-Key (ADR-0012) | `edacommon/idempotency.py` |
| Claim check (ADR-0009) | `edacommon/claimcheck.py`; invoices in `order_svc`, manifests in `fulfilment_svc`, labels in `shipping_svc`; consumers in `notification_svc` (verified attachments) and `returns_svc` (pre-signed label URL) |
| Webhooks: HMAC, 300 s tolerance, inbox dedupe, store-then-ack | `edacommon/webhooks.py`; PSP webhooks in `payment_svc`, carrier webhooks in `shipping_svc` |
| W3C trace context through outbox and headers; consumer span with parent and link (ADR-0011) | `edacommon/tracing.py` |
| Metric contract of guide §8 | `edacommon/metrics.py` (names, units and buckets are tested against the contract) |
| JSON logs and PII redaction (guide §6.4, ADR-0013) | `edacommon/logging.py` |
| Problem details, health, OIDC/JWT, `AUTH_MODE=none` refused outside local | `edacommon/http.py`, `config.py` |
| CQRS read models (ADR-0010) | checkout's `catalog_view`; order-svc's `adapters/projector/`; returns-svc's `eligibility_view` |

## Checklist status (guide §11)

| Item | Status |
|---|---|
| Dependency rule enforced; domain has no framework imports | done (import-linter, 5 contracts) |
| Shared tables match `common-tables.sql` (`information_schema` diff) | done, in edacommon and in every service's own migrations |
| Every saga transition tested; late, duplicate and out-of-order replies | done (`order_svc/tests/unit/test_order_saga.py`, `returns_svc/tests/unit/test_returns_saga.py`) |
| Property test: random interleavings end terminal or in attention, with consistent compensations | done (Hypothesis with participant models; 400 examples in CI, 4,000 run once) |
| Money arithmetic, banker's rounding, mixed currencies rejected | done (checkout and order domains) |
| Golden `.bin` ↔ `.json` byte-for-byte; wire format through the registry | done for all 54 messages |
| Produced messages validated, envelope fields asserted | done in every service's integration tests |
| Unknown `ce_type` ignored; enum `UNKNOWN` handled | done |
| HTTP responses validate against OpenAPI | done with a JSON Schema validator over the contract documents (`edacommon.testing.openapi`); **schemathesis not used** (see unfinished work) |
| Command in → reply out, duplicate, resend, crash before offset commit | done (processor tests with real Postgres; crash test with real Kafka) |
| Transient in place / RetryLater → `.retry.10s` with headers and bytes / NonRetryable → `.dlq` / DLQ replay processed once | done, with real Kafka |
| Trace context parent + outbox carries the new context | done |
| Polling relay order, headers, murmur2 partitioning | done (headers checked against the connector JSON; partition checked on a real 12-partition topic) |
| Debezium connector in a container | **not done**: no Docker and no Connect here |
| Graceful shutdown | done (loop test with real Kafka; process smoke test with SIGTERM) |
| checkout-svc: replay same orderId, different body 422, concurrent 409, price mismatch 422 | done |
| inventory-svc: last-unit race, TTL expiry restores stock, commit after expiry | done |
| payment-svc: decline, timeout → authorised, timeout → `PSP_TIMEOUT` + void, ×3 webhooks, late success voided, bad signature 401 | done |
| order-svc: deterministic invoice key, gapless numbers, `GET /orders/{id}` fallback | done |
| projector: replay equals incremental, stale versions dropped | done |
| fulfilment-svc: dropped request recovered by resend, no duplicate pick order; manifest uploaded before `OrderPacked`, hash verified by a consumer | done (plus: event under 2 KB, S3 outage holds the WMS event, cancel tombstone, cancel after dispatch to DLQ) |
| shipping-svc: out-of-order and duplicate carrier webhooks yield monotonic, unique events | done (all 24 arrival orders ×2 in a unit test; ×2 duplicates + swapped send order through the real webhook endpoint; bad signature/stale 401, bad body 400) |
| returns-svc: eligibility (not delivered, window closed, over-quantity), partial refund, refund retry schedule, manual decision | done (plus every saga-table row, a Hypothesis interleaving test, gapless RMA numbers, expiry gives quantity back) |
| notification-svc: one email per triggering event under duplicates; no PII in logs | done (×3 redelivery + a re-emitted fact = one email; captured logs grepped for email, name and street) |
| Metrics with exact names and buckets; JSON logs without PII | done (in-memory reader; captured logs grepped) |
| Component suite (layer 4) | not in scope for this wave |

## Adding a service

Copy inventory-svc, which is the smallest complete participant. payment-svc is the template for a service with a fake external system and webhooks; order-svc is the template for an orchestrator, and returns-svc should follow it.

1. `services/<name>_svc/pyproject.toml` (dependencies `edacommon`, `contracts-py` plus pinned extras). Add the package to the root `pyproject.toml` (`dependencies`, `[tool.uv.sources]`, the mypy paths, the import-linter `root_packages` and contracts).
2. `migrations/`: copy `env.py`, `script.py.mako`, `alembic.ini`. `0001_common_tables.py` calls `upgrade_common(op, saga=<orchestrator?>)`. Private tables go in `0002` as explicit SQL.
3. `domain/`: pure dataclasses and decision functions, standard library only, with `now` passed in.
4. `application/`: ports (Protocols), use cases that take ports, and `messages.py` that builds `OutgoingMessage` / `PendingMessage` from domain decisions with the generated record classes (`R.X.TOPIC`, `R.X.AVRO_NAME`).
5. `adapters/inbound/messaging/handlers.py`: `HandlerRegistry` with one `@reg.handler(R.SomeCommand)` per consumed type. `TOPICS` lists the subscribed topics. Fakes go in `adapters/outbound/<external>/fake/` and get their knobs from config and the admin API.
6. `main.py`: build `Infrastructure.from_settings`, `consumer_loops`, `create_app` with the routers plus `dlq_router`, `Readiness` (database, consumer, `SchemaReadiness` over the produced types), and workers (`PeriodicTask`, `infra.relay()`, `infra.housekeeping()`).
7. Tests: unit tests on the domain; integration tests through `edacommon.testing.service.ServiceHarness`, which uses real Postgres with your migrations, the real processor and the polling relay, a fake broker and the in-memory registry.

## Decisions taken in this build (beyond the contracts)

Wave 2 decisions are in each service's README. The ones that cross service lines:

- **The WMS and the carrier are called like the PSP:** inside the consumer transaction, idempotent on `fulfilmentId` / `shipmentId`. The fake WMS reports progress through `poll`/`ack`, and an event is acknowledged only after its commit. The fake carrier posts signed webhooks to the real endpoint.
- **shipping-svc mints the outbound `shipmentId`** (one shipment per `fulfilmentId`). returns-svc mints the return `shipmentId`, as `IssueReturnLabel` says.
- **notification-svc dedupes on template + business id** as well as on the inbox, so a re-emitted fact sends no second email.
- **returns-svc runs pass-through states in the request transaction** and answers `POST /returns` with the status after them (`AWAITING_PARCEL` or `MANUAL_REVIEW`).

- **The PSP is called inside the consumer transaction**, after the payment row is written. That is safe because the call is idempotent on `paymentId`/`refundId` (ADR-0006 layer 3). The cost is a transaction held open for up to the PSP timeout. See `payment_svc/README.md`.
- **Idempotency "still running" detection** uses a transaction-scoped advisory lock on `(caller, key)`. With it, a concurrent duplicate gets an immediate 409, as the checklist requires, while the `IN_PROGRESS` row is still written in the business transaction as ADR-0012 says.
- **`aggregateVersion` stays strictly increasing per order**: a transition that emits *n* events advances `saga_instance.version` by *n*.
- **A reply that arrives before its saga exists** (no order across topics) raises `RetryLater`, so it waits on the retry topics for `CheckoutSubmitted`.
- **inventory-svc caps the requested TTL with `RESERVATION_TTL`** (the `min` of the two). That is what makes the §5.7 drill (`RESERVATION_TTL=60s`) work while the saga still asks for 900 s.
- **`AUTH_MODE=none`:** a request with `X-Debug-Subject` acts as that customer (scope `shop`). A request without it is a local operator with every scope.
- **OpenTelemetry SQLAlchemy instrumentation is skipped**: the pinned SQLAlchemy 2.1 is outside the instrumentor's declared support, and it would do nothing. HTTP and consumer spans are unaffected.

## Unfinished in wave 1 / known gaps

- Wave 2 fakes (WMS, carrier, mail) keep state in memory, like the fake PSP. Restarting a service forgets in-flight pick orders and tracking plans. Saga resends repair pick orders; tracking plans do not come back.
- notification-svc does not use the `notification-tmp` bucket, and has no SMS or push channel. Contact erasure (`CustomerErased`) is not in the contracts.
- A lost `ReturnInspected` has no timer (architecture §6.1 defines none). It is visible in `GET /ops/sagas/{id}` only.
- No Debezium-in-a-container test and no MinIO-container test (no Docker here); claim checks are tested against moto.
- No real Schema Registry test. The Testcontainers path does not start one either; the serde is tested with the mock client.
- schemathesis property tests are not wired. Responses are validated against the OpenAPI schemas in the service tests instead.
- The fake PSP's `tok_timeout` answers immediately with a timeout instead of sleeping the 5 s client timeout. The behaviour is the same and the tests stay fast.
- The Dockerfile has not been built (no Docker daemon).
- Real OIDC was not exercised against Keycloak. JWT validation is implemented with PyJWT and JWKS, but it is not tested end to end.

## Contract observations

Wave 2:

- `OrderPlaced` has no shipping fee. returns-svc derives it as total − sum(line totals), which is correct only because prices are VAT-inclusive. Adding `shippingFee` to `OrderPlaced` would remove the inference.
- `OrderDelivered.returnWindowEndsAt` (computed by order-svc, which has no window setting) and `RETURN_WINDOW_DAYS` (returns-svc) are two sources for one policy. This build uses returns-svc's setting.
- `ShipmentException` has no `returnId`, so returns-svc finds the saga by `shipmentId`. `ExpectReturn` has no reply event, so the saga cannot know whether the warehouse got it; returns-svc resends it with every label resend.
- `Return.status` has no value for a return closed by `CLOSE_WITHOUT_REFUND`. This build reports `REJECTED`; `ReturnClosed.outcome` is `MANUAL_REVIEW`.
- `saga_transition.trigger_type` is documented as "event type, DEADLINE, or OPERATOR". returns-svc also writes `HTTP` (the start) and `AUTO` (pass-through steps).
- architecture §6.3 shows `POST /returns` answering `status REQUESTED`; see the decision above.
- `POST /admin/fakes/carrier/.../advance` has no way to choose an exception code. This build accepts an optional `exceptionCode`.

Wave 1:

- `contracts/tools/contracts.py` gives the example timestamp as "2026-11-18T09:46:40Z", but `1_795_000_000_000` ms is 2026-11-18T**11:06:40Z**. Only the comment is wrong; the golden bytes are consistent.
- The format of `x-not-before` (and the other `x-*` values) is not fixed anywhere. This build writes RFC 3339 UTC with milliseconds and `Z` (`2026-11-18T11:06:50.000Z`) and integers in decimal. The Java build must agree, or the contracts should say so.
- Debezium writes a null-valued header for a null `causation_id`/`tracestate`; the polling relay does the same. The Java build should check that it tolerates null header values.
- `checkout.yaml` lets `PUT /carts/{id}/items/{sku}` return 422 when the quantity exceeds advisory availability. With the seed, SKU-1006 (onHand 0) therefore cannot reach a cart, so the "OUT_OF_STOCK cancellation" drill is only reachable through the SKU-1005 race. You may want to relax the cart check, or the seed comment.
- Which aggregate an envelope names on `CheckoutSubmitted` is not specified. This build uses `aggregateType=Checkout`, `aggregateId=checkoutId`, `partitionKey=orderId`; the golden example uses the key for both.
