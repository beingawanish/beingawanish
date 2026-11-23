# eda-commerce: an event-driven e-commerce capstone and enterprise template

eda-commerce is a working e-commerce backend built from nine services that talk to each other only through Kafka. It is meant to be hand-built by one senior engineer in 10 working days, then reused as a template. Two more teams will build it again, once in Python and once in Java, from the same contracts. The two builds must interoperate: a Python service consumes a Java service's events and the other way round.

This directory holds everything those builds share: the design, the contracts, the infrastructure and the decisions. It deliberately holds **no service code**.

The domain is real, and so is the trouble. The payment provider declines, times out and sends duplicate webhooks. The warehouse is slow and loses requests. The carrier sends tracking updates twice and out of order. The design has to absorb all of that without losing an order, charging twice or shipping something unpaid. Most of the interesting code is about exactly that.

## What is in the box

```
eda-commerce/
├── README.md                      you are here: overview, how to run, 10-day plan, template guide
├── Makefile                       up / down / topics / schemas / connectors / seed / chaos-* / contracts
├── docs/
│   ├── architecture.md            context map, ownership, sagas, sequence diagrams, topics, consistency, SLOs, chaos drills
│   ├── implementation-guide.md    module layout, shared libraries, interop rules, config, metrics, test checklist
│   └── adr/                       16 architecture decision records + template
├── contracts/
│   ├── topics.yaml                topic catalogue: the single source of truth for Kafka
│   ├── avro/                      hand-written Avro schemas (common types, events, commands)
│   ├── avro-bundled/              generated self-contained schemas (registered, used for codegen)
│   ├── examples/                  generated golden messages: JSON + raw Avro .bin per message
│   ├── asyncapi/asyncapi.yaml     generated AsyncAPI 3.0 document for every topic and operation
│   ├── openapi/                   OpenAPI 3.1: checkout, orders, returns, catalog, webhooks, admin
│   ├── sql/common-tables.sql      outbox, inbox, idempotency and saga tables every service creates
│   └── tools/contracts.py         validate / bundle / examples / asyncapi / topics-conf / check
└── infra/
    ├── docker-compose.yml         Kafka (KRaft), Schema Registry, Debezium Connect, Postgres, MinIO,
    │                              OTel Collector, Jaeger, Prometheus, Grafana, Kafka UI, kafka-exporter,
    │                              optional Temporal and Keycloak profiles
    ├── compose.apps.example.yml   how service containers attach (and the env var contract)
    ├── topics.conf                generated from contracts/topics.yaml
    ├── postgres/ connect/ otel/ prometheus/ grafana/ minio/ keycloak/ seed/
    ├── scripts/                   create-topics, register-schemas, register-connectors, seed, chaos, health
    └── k8s/                       Kustomize base, KEDA lag-scaler component, example overlay (starting point)
```

## Bounded contexts

| Context | Service | In one sentence |
|---|---|---|
| Catalog & Pricing | catalog-svc | Owns products and prices; publishes them as compacted snapshots that others keep as read models. |
| Cart & Checkout | checkout-svc | Prices carts from its local catalog view and turns a cart into `CheckoutSubmitted`, minting the orderId. |
| Order | order-svc (+ order-history-projector) | Orchestrates the order saga, issues invoices, serves order status from a CQRS read model. |
| Payment | payment-svc | Authorises, captures, voids and refunds through a PSP adapter; the fake PSP declines, times out and duplicates webhooks. |
| Inventory | inventory-svc | Reserves stock with a TTL, commits it after authorisation, publishes availability. |
| Fulfilment / Warehouse | fulfilment-svc | Pick, pack, dispatch, and returns intake; the fake WMS is slow and lossy; packing manifests go by claim check. |
| Shipping | shipping-svc | Books carriers and labels, normalises duplicated and reordered carrier webhooks. |
| Notification | notification-svc | Sends customer emails with invoice and label attachments; owns contact details. |
| Returns & Refunds | returns-svc | Orchestrates the reverse saga: eligibility, label, inspection, restock, partial or full refund. |

Details, the context map and data ownership: [docs/architecture.md §2–3](docs/architecture.md).

## End-to-end flows

**Order (orchestrated by order-svc, with a choreographed warehouse ↔ carrier hand-off):**

1. `POST /checkouts` with an `Idempotency-Key` returns `202` and an orderId at once.
2. Reserve stock (TTL 15 min) → authorise payment → commit the reservation → `OrderConfirmed` → request fulfilment.
3. Warehouse picks and packs, and uploads the packing manifest (claim check). Shipping books a label. The parcel is dispatched.
4. **Pivot:** on dispatch the saga captures payment. Before this point every step is compensated on failure. After it, steps are only retried, or handed to a human.
5. Invoice PDF goes to object storage and `InvoiceIssued` carries the claim check. The carrier delivers and `OrderDelivered` opens the 30-day return window.

**Return (orchestrated by returns-svc, forward-recovery):** request → auto-approve or manual review → return label → parcel received → inspection per line → restock the sellable items and refund the computed amount → closed as REFUNDED, PARTIALLY_REFUNDED, REJECTED or EXPIRED.

**Failure branches designed and drawn** in [architecture §5–6](docs/architecture.md): out of stock, payment declined, PSP timeout with reconciliation, duplicate webhooks, reservation expiry racing a slow payment, warehouse losing requests, fulfilment failure after confirmation, capture failure after dispatch, carrier webhooks out of order, refund failures with manual decision.

## Running the infrastructure

Prerequisites: Docker with Compose v2.20+, GNU make, `curl`, `jq`, Python 3.10+ (stdlib only for the scripts; `pip install -r contracts/tools/requirements.txt` for the contract tooling). About 6 GB of free RAM for the core stack.

```bash
make up            # core stack; waits for health checks; creates MinIO buckets
make topics        # 15 business topics + 40 retry/DLQ topics from infra/topics.conf
make schemas       # registers 54 subjects (FULL_TRANSITIVE, compatibility-checked first)
make health        # one line per component
```

Then start services (one build, or a mix) and finish the bootstrap:

```bash
# run each service on the host (ports 8101–8109) or with infra/compose.apps.example.yml
make connectors    # after services have run their first migration (it creates outbox + publication)
make seed          # products, prices and stock through the services' admin APIs
```

| UI / endpoint | URL | Credentials |
|---|---|---|
| Kafka UI (topics, consumer groups, schemas, connectors) | http://localhost:8080 | none |
| Grafana (dashboard "eda-commerce: backbone, sagas, SLOs") | http://localhost:3000 | admin / admin (anonymous viewer on) |
| Jaeger | http://localhost:16686 | none |
| Prometheus (alerts under /alerts) | http://localhost:9090 | none |
| MinIO console | http://localhost:9001 | minioadmin / minioadmin |
| Schema Registry | http://localhost:8081 | none |
| Kafka Connect REST | http://localhost:8083 | none |
| Postgres | localhost:5432 | `<context>_svc` / same as user; superuser postgres / postgres |
| Temporal UI (`make up-all`) | http://localhost:8233 | none |
| Keycloak (`make up-all`) | http://localhost:8180 | admin / admin; customer jane / jane |

Other targets: `make down` (keep data), `make clean` (delete volumes), `make logs SVC=connect`, `make chaos` (list drills), `make contracts` / `make contracts-check`, `make k8s-render`.

**Changing contracts.** Edit `contracts/avro/**` or `contracts/topics.yaml`, then `make contracts` to regenerate bundled schemas, golden examples, AsyncAPI and `topics.conf`, then `make schemas`. CI runs `make contracts-check`. It fails if anything generated is stale or a lint rule is broken (envelope first, null-first optional unions with null defaults, enum defaults, every message on exactly one topic, the key field present in every message).

## How the two implementations map to this design

Both builds live next to this directory (`impl-python/`, `impl-java/`). They share everything in `contracts/` and `infra/`, and they follow the same hexagonal layout and shared-library modules ([implementation guide](docs/implementation-guide.md)).

| Concern | Python build | Java build | Shared, fixed by |
|---|---|---|---|
| HTTP API | FastAPI + pydantic | Spring Web MVC | `contracts/openapi/` |
| Persistence and migrations | SQLAlchemy 2 + Alembic | Spring Data JPA + Flyway | `contracts/sql/common-tables.sql` |
| Kafka client | confluent-kafka (librdkafka) | Spring Kafka | `contracts/topics.yaml`, guide §7.1 |
| Avro | confluent `AvroSerializer` + fastavro, dict records | Confluent `KafkaAvroSerializer`, generated SpecificRecord | `contracts/avro-bundled/`, ADR-0004 |
| Outbox relay | Debezium (shared), polling relay fallback in `edacommon` | same | ADR-0003 |
| Saga engine | DB state machine in `edacommon.saga` | same, in `edacommon` | ADR-0008 |
| Observability | OpenTelemetry SDK | OpenTelemetry starter/agent | guide §8 metric contract |
| Tests | pytest + Testcontainers + Hypothesis | JUnit 5 + Testcontainers + jqwik + ArchUnit | guide §11 checklist |

**Mixed mode** is a first-class scenario: any service may run in either language, so long as one service is never run in both at once against the same database. The Day 10 interop drill proves it. The traps that break mixed mode (partitioner, subject strategy, schema normalisation, timestamps, header names) are listed in [guide §5](docs/implementation-guide.md#5-interoperability-rules-python--java).

## Architecture decision records

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-hybrid-orchestration-and-choreography.md) | Orchestrate compensating flows, choreograph the rest |
| [0002](docs/adr/0002-kafka-as-event-backbone.md) | Kafka (KRaft), not RabbitMQ |
| [0003](docs/adr/0003-transactional-outbox-with-debezium.md) | Transactional outbox relayed by Debezium; polling relay as fallback |
| [0004](docs/adr/0004-avro-schema-registry-full-transitive.md) | Avro + Schema Registry, FULL_TRANSITIVE, TopicRecordNameStrategy |
| [0005](docs/adr/0005-topic-layout-and-partition-keys.md) | One event topic per context, command topic per service, orderId key |
| [0006](docs/adr/0006-idempotent-consumers-with-inbox.md) | Inbox table plus idempotent business ids |
| [0007](docs/adr/0007-retry-topics-and-dlq.md) | In-place retry, per-group retry topics, per-group DLQ |
| [0008](docs/adr/0008-saga-orchestrator-db-state-machine.md) | DB-backed saga state machine by default; Temporal as option B |
| [0009](docs/adr/0009-claim-check-for-large-payloads.md) | Claim check in object storage for documents and big payloads |
| [0010](docs/adr/0010-cqrs-read-models.md) | Read models for catalog-at-checkout and order history |
| [0011](docs/adr/0011-observability-opentelemetry.md) | OpenTelemetry → Jaeger + Prometheus/Grafana, uniform metric contract |
| [0012](docs/adr/0012-edge-api-rest-idempotency-keys.md) | REST at the edge with Idempotency-Key and 202 Accepted |
| [0013](docs/adr/0013-security-oidc-mtls-pii.md) | OIDC at the edge, mTLS and ACLs inside, minimal PII in events |
| [0014](docs/adr/0014-testing-strategy.md) | Pure domain tests, golden-message contract tests, Testcontainers, chaos drills |
| [0015](docs/adr/0015-authorize-at-checkout-capture-at-dispatch.md) | Authorise at checkout, capture at dispatch (the pivot) |
| [0016](docs/adr/0016-inventory-reservations-with-ttl.md) | Reservations with TTL, committed after authorisation |

## The 10-day build plan

The plan assumes one experienced engineer building one language. Each day ends with acceptance criteria you can demonstrate, not just "code written". If a day slips, cut scope from the *next* day's service-specific extras, never from the acceptance criteria of the shared library: Days 1–2 carry everything else.

Every day also ends with the same three checks: `make contracts-check` passes, the service test suites pass, and the Grafana dashboard shows the day's traffic.

### Day 1: Infrastructure, contracts and serialisation

Build: bring up the stack, create topics, register schemas. Start `edacommon`: `ids` (UUIDv7), `envelope`, `serde` (Schema Registry, TopicRecordNameStrategy, no auto-registration), `logging`, and `metrics` instrument registration. Set up the repository skeleton for all nine services with the hexagonal layout and the architecture test.

Acceptance:

- `make up topics schemas` succeeds on a clean machine; `make health` is all "up"; Kafka UI shows the 55 catalogue topics (15 business, 40 retry/DLQ) and 54 subjects.
- A unit test decodes **every** `contracts/examples/*.bin` with your Avro code and matches its `.json`; encoding the `.json` reproduces the bytes.
- Serialising a record with the serde produces the Confluent wire format with the registered schema id (Testcontainers Schema Registry or the compose one).
- The layer-dependency test (import-linter or ArchUnit) runs and passes for an empty service skeleton.

### Day 2: Outbox, inbox and the consumer runtime

Build: `outbox` writer and polling relay; Debezium connector for one service; `consumer` runtime (§4.1 of the guide) with inbox, unit of work, error classification, in-place retry, retry-topic and DLQ forwarding, retry consumer, `/ops/dlq` endpoints; `tracing` propagation through outbox and headers.

Acceptance:

- A test service writes a business row and an outbox row in one transaction; the event appears on its topic via Debezium with all `ce_*`, correlation and trace headers (architecture §8.3).
- Rolling back the transaction publishes nothing.
- Delivering the same message twice causes one effect; `eda_consumer_processed_total{outcome="duplicate"}` increments.
- A handler raising `RetryLater` moves the message through `.retry.10s` → `.retry.1m` → `.retry.10m` → `.dlq` with raw bytes unchanged and `x-*` headers set; `POST /ops/dlq/replay` brings it back once.
- Jaeger shows one trace spanning producer span → consumer span across the outbox.
- `make chaos-connect DURATION=60` while writing: zero lost events after recovery.

### Day 3: Catalog, read models and carts

Build: catalog-svc (products, prices, admin API, browse API, outbox to compacted topics, stock-level projection); checkout-svc catalog read model from compacted topics; cart API with ETags.

Acceptance:

- `make seed` (catalog part) results in one record per SKU on `catalog.product.v1` and `catalog.price.v1`.
- Deleting checkout's `catalog_view` and restarting with a new group id rebuilds it from offset 0 to the same content.
- Cart endpoints match `contracts/openapi/checkout.yaml` (schema validation test); a discontinued SKU (SKU-1007) is refused with 422; `pricedAt` reflects read-model freshness.
- A price change propagates to the cart view in under 2 seconds (event age panel).

### Day 4: Checkout submit, inventory and the saga kit

Build: `POST /checkouts` with the `idempotency` middleware and `expectedTotal`; inventory-svc (stock, reservations with TTL, sweeper, commit, release, stock-level topic, admin API); `edacommon.saga` (repository, transition log, deadline sweeper, ops endpoints); order-svc saga skeleton through RESERVING_STOCK.

Acceptance:

- Same Idempotency-Key and body → same orderId and `Idempotent-Replayed: true`; different body → 422; concurrent → 409.
- Two concurrent checkouts for SKU-1005 (1 unit): exactly one gets `StockReserved`, the other ends `CANCELLED(OUT_OF_STOCK)`.
- A reservation left alone expires after the TTL, emits `ReservationExpired` and restores availability on `inventory.stock-level.v1`.
- Killing order-svc between receiving `CheckoutSubmitted` and committing leaves no duplicate `ReserveStock` effect after restart.
- `GET /ops/sagas/{orderId}` shows the transition history.

### Day 5: Payment and the decision half of the saga

Build: payment-svc with the PSP port, fake PSP (magic tokens, runtime knobs via `/admin/fakes/psp`), webhook endpoint (HMAC, inbox, store-then-ack), reconciliation of unknown outcomes; order saga through AUTHORIZING_PAYMENT, COMMITTING_STOCK, CANCELLING, and `OrderConfirmed`.

Acceptance:

- `tok_visa_ok` → `OrderConfirmed` within 5 s; `tok_decline` → `CANCELLED(PAYMENT_DECLINED)` and the reservation released.
- `tok_timeout` → reconciliation runs; the order ends confirmed or `PSP_TIMEOUT`-cancelled with a void, never both, in under 4 minutes.
- `tok_dup_webhook` → exactly one `PaymentAuthorized` on the topic.
- `tok_slow` with inventory-svc at `RESERVATION_TTL=60s` (webhook after 90 s) → `CANCELLED(RESERVATION_EXPIRED, paymentVoided=true)`.
- A webhook with a bad signature → 401; a stale timestamp → 401.
- Domain tests cover every row of the order saga table up to `OrderConfirmed`, including late replies.

### Day 6: Fulfilment, shipping, capture and documents

Build: fulfilment-svc with fake WMS (drop rate, delays), pick/pack/dispatch, packing manifest via `claimcheck`; shipping-svc with label booking (label PDF by claim check), fake carrier with duplicates and reordering, carrier webhook normalisation; order saga AWAITING_FULFILMENT_ACK (resends), FULFILLING, PACKED, CAPTURING, SHIPPED, DELIVERED; invoice rendering and `InvoiceIssued`.

Acceptance:

- A `tok_visa_ok` order reaches `DELIVERED` with the default fake settings, end to end, without manual steps.
- With `make chaos-wms` the saga resends `RequestFulfilment`; no order has two pick orders in the fake WMS; orders beyond 3 resends show `NEEDS_ATTENTION`.
- The packing manifest (2,000 lines by default) is in MinIO; the `OrderPacked` message is under 2 KB; a consumer verifies the SHA-256.
- With `make chaos-carrier` every order gets exactly one `ShipmentDelivered`; tracking never moves backwards.
- `tok_capture_fails` → `NEEDS_ATTENTION` and `OrderRequiresAttention` after dispatch, with no compensation attempted.
- The invoice PDF opens from `GET /orders/{id}/invoice` via a pre-signed URL; invoice numbers have no gaps.

### Day 7: Order history read model, notifications and observability

Build: order-history-projector (separate process, own group); `GET /orders/{id}` with write-model fallback and `GET /customers/me/orders`; notification-svc (contact store from `OrderPlaced`, templates, attachments from claim checks, `NotificationSent`); finish metrics so every dashboard panel is populated.

Acceptance:

- Right after `POST /checkouts`, `GET /orders/{id}` returns `PENDING` with `source: WRITE_MODEL_FALLBACK`; after a moment, `READ_MODEL` with the timeline.
- Rebuilding the projection from offset 0 into a fresh schema yields identical rows.
- Emails (written to the fake mail outbox or logs) arrive once per trigger even under `make chaos-psp-duplicates`; the invoice email carries the PDF.
- Every panel on the Grafana dashboard shows data under a 2 orders/s load; the p99 event age panel is under 2 s.
- A captured log sample contains no email address, name or street.

### Day 8: Returns and refunds (the reverse saga)

Build: returns-svc with the eligibility projection, `POST /returns` with idempotency, auto-approval rule and ops decision endpoint, the returns saga (label, expect return, inspection, restock, refund, retries, REFUND_REVIEW); fulfilment returns intake and inspection fake; payment refunds; shipping return labels.

Acceptance:

- A return inside the window for a delivered order runs to `REFUNDED`; the refund equals the line totals; `ItemsRestocked` restores stock.
- A return with one item inspected DAMAGED and reason CHANGED_MIND ends `PARTIALLY_REFUNDED` with the damaged line excluded.
- Requests outside the window, before delivery, or above the remaining quantity → 422 with a clear problem type.
- A value above the auto-approve limit waits in `MANUAL_REVIEW` until `POST /ops/returns/{id}/decision`.
- Forcing refund failures runs the 1 min / 10 min / 1 h schedule with the same `refundId`, then `REFUND_REVIEW`; `RETRY_REFUND` completes it; the PSP fake shows one refund, not several.
- The return label email has the PDF attached.

### Day 9: Chaos drills and failure hardening

Build: nothing new. Run every drill in [architecture §11](docs/architecture.md#11-chaos-drills) under load and fix what breaks. Write a short report per drill: what happened, what the dashboard showed, pass or fail, fix.

Acceptance:

- Every drill in the table passes its criteria.
- After all drills and a 10-minute settle: zero `eda_saga_overdue`, zero unexplained DLQ entries, stock levels equal seed minus delivered plus restocked, and every 202 order has a terminal or attention state (SLO 10 reconciliation query returns nothing).
- The alert rules fired where expected (lag during `chaos-kafka`, DLQ during a deliberate poison message) and resolved afterwards.

### Day 10: Contracts in CI, interop, deployment and the handover

Build: CI pipeline (`make contracts-check`, schema compatibility against a registry, unit, contract and Testcontainers suites, the component suite nightly); the interop drill with the other language's build if available, otherwise against the golden messages only; deploy one service to a local Kubernetes cluster (kind or k3d) with the Kustomize overlay; review every ADR's "when to revisit" against what you learned.

Acceptance:

- CI is green and blocks a deliberately incompatible schema change (for example, a new required field without a default).
- Mixed deployment (order-svc in one language, payment-svc and inventory-svc in the other) passes the happy and decline paths. If the other build does not exist yet, the golden-message tests pass and the gap is recorded.
- `kubectl kustomize infra/k8s/overlays/local-example` renders; the deployed service becomes ready, scales on lag with KEDA (if installed) and survives `kubectl drain` with one rebalance at a time.
- Every item of the implementation guide's test checklist is ticked for every service, or has a written exception.
- ADRs updated where reality disagreed with them.

**Stretch goals, if time remains:** customer-initiated cancellation before dispatch (`CUSTOMER_REQUESTED` is already in the enum); crypto-shredding for PII fields (ADR-0013); a Temporal implementation of the order saga behind the same contracts (ADR-0008 option B); split shipments with partial capture (ADR-0015); SSE push of order status.

## Using this as a template for another domain

The domain is e-commerce, but most of this directory is domain-neutral. Roughly 70 % carries over as is.

**Keep unchanged:**

- The shared library modules and their behaviour (guide §4): envelope, serde, outbox, inbox, consumer runtime, retry/DLQ, saga kit, idempotency keys, claim check, tracing, webhooks.
- `contracts/avro/common/Envelope.avsc`, `ClaimCheck.avsc`, `Money.avsc`, and the shared tables in `contracts/sql/common-tables.sql`.
- `contracts/tools/contracts.py`, the topic naming rules, the retry policy and the lint rules.
- The infrastructure stack, scripts, Makefile, dashboards (metric names are domain-neutral) and the k8s base.
- ADR-0002, 0003, 0004, 0006, 0007, 0009, 0011, 0012, 0014 almost word for word. Re-read their "when to revisit" sections against the new domain.

**Replace:**

1. **Contexts and ownership.** Run an event-storming session. List the aggregates and who owns them. Write the new architecture §2–3.
2. **The key.** Pick the business identifier that ties one flow together (claimId, shipmentId, loanApplicationId). It becomes the partition key of every flow topic (re-decide ADR-0005).
3. **Sagas.** Find the flows that move money, stock, capacity or legal status. Those get orchestrators. Find the **pivot** of each: the step after which you can only go forward (ADR-0015 is the e-commerce example). Write the state table before any code.
4. **Topics.** Rewrite `contracts/topics.yaml`: one event topic per context, one command topic per orchestrated participant, compacted topics for reference data. Run `make contracts`.
5. **Schemas.** Write the events and commands under `contracts/avro/<context>/`. Tag personal data with `"pii": true`.
6. **Fakes.** For every external system, write down its realistic failure modes (decline, timeout with unknown outcome, duplicates, reordering, silence) and give its fake the same knobs. This is what turns the template from a demo into a rehearsal.
7. **Domain ADRs.** Replace ADR-0015 and ADR-0016 with the new domain's equivalents. Typical examples: "approve before disbursing" for lending, "hold a slot with a TTL" for bookings, "quote then bind" for insurance.
8. **SLOs and drills.** Restate the SLO table in business terms ("time to decision", "no accepted request lost") and adapt the chaos table to the new externals.
9. **Service names, databases, connectors.** Update `infra/postgres/init/01-databases.sh` (the `SERVICES` list), one connector JSON per service, the ports, and `compose.apps.example.yml`.

A quick mapping to calibrate:

| e-commerce | Food delivery | Insurance claims | Hotel booking |
|---|---|---|---|
| Order saga | Order → restaurant accept → courier assign → deliver | FNOL → assess → approve → pay out | Hold room → pay → confirm |
| Reservation with TTL | Courier slot hold | Reserve (financial) | Room hold |
| Pivot: dispatch | Food picked up | Payment sent | Check-in |
| Returns saga | Refund for missing items | Subrogation / recovery | Cancellation and refund |
| Fake PSP / WMS / carrier | Fake PSP / restaurant tablet / courier app | Fake bank / loss adjuster / repair shop | Fake PSP / channel manager |

## Kubernetes

`infra/k8s/` is a **starting point**, not a production deployment. The base gives each service a Deployment (non-root, read-only root filesystem, probes, graceful shutdown tuned for consumer groups), Service, CPU-based HPA, PodDisruptionBudget (one pod at a time, so drains cause one rebalance at a time), NetworkPolicy and ConfigMap. The `keda-lag-scaler` component swaps the HPA for a KEDA `ScaledObject` that scales on consumer lag, capped at the partition count. The example overlay deploys payment-svc.

Not included, on purpose: ingress, mesh mTLS policy, secrets management, Kafka topic and ACL CRDs, database provisioning. ADR-0013 says what they must provide.

## Status of this design package

- All Avro schemas parse and pass lint; golden examples round-trip with fastavro; the AsyncAPI document validates with the AsyncAPI parser (3.0.0); all OpenAPI documents validate with openapi-spec-validator; the shared SQL parses with the PostgreSQL parser (pglast); `docker compose config` passes for the stack and the apps example.
- Container image tags are pinned but were not pulled in the authoring environment. On first `make up`, if a tag is missing from a registry, bump it in `infra/docker-compose.yml` and re-run the Day 1 and Day 2 acceptance checks.
- The OpenTelemetry Collector config, Prometheus rules and Kustomize overlay were checked as YAML only. Validate them on Day 1 with `otelcol-contrib validate`, `promtool check rules` and `kubectl kustomize`.
