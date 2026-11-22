# ADR-0008: Saga orchestrator as a database-backed state machine (Temporal kept as option B)

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0001, ADR-0003, ADR-0006, contracts/sql/common-tables.sql (saga_*), docs/architecture.md §5–6

## Context

order-svc and returns-svc orchestrate long-running flows: seconds for the payment decision, days until delivery, weeks for a return. They need durable state, timers (deadlines), retries with backoff, compensation, and a way for humans to inspect and nudge a stuck instance.

Two credible ways exist:

- **A. Database-backed state machine.** Saga state is a row. Each incoming event triggers one transition in one transaction that also writes outbox rows. Deadlines are a column swept by a timer.
- **B. A workflow engine (Temporal).** The saga is code (a workflow) that "waits" for signals; the engine persists history, timers and retries. Kafka consumers translate events into signals; activities publish commands.

Both implementations (Python and Java) must behave identically and interoperate on the same topics.

## Decision

**Default: option A, a database-backed state machine** in each orchestrator, built on the shared tables `saga_instance` and `saga_transition`.

- The state machine is a pure function in the domain layer: `(state, data, event) → (new state, new data, [commands], [events], deadline)`. No I/O, trivially unit-testable, and the same table of transitions in both languages (architecture §5.2 and §6.1 are the spec).
- The application layer loads the row with optimistic locking (`version`), applies the function, writes the row, a transition row and the outbox rows **in one transaction** with the inbox insert.
- A **deadline sweeper** runs every 5 s in each instance: `SELECT … WHERE deadline_at <= now() ORDER BY deadline_at FOR UPDATE SKIP LOCKED LIMIT 100`. Each due saga gets a synthetic `DEADLINE` trigger through the same transition function. Several instances sweep in parallel without double work.
- Ops endpoints (`/ops/sagas/{id}`, `/ops/sagas/{id}/retry-step`) read and nudge instances.

**Option B, Temporal,** stays available. `docker compose --profile temporal` starts a Temporal server and UI. A team may implement the order saga as a Temporal workflow **as long as the Kafka contract is unchanged**: same commands out, same replies in, same events, same ids. A Kafka consumer signals the workflow by `orderId`; activities write commands to the service's outbox (so the outbox guarantee still holds).

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it as default |
|---|---|---|
| **B. Temporal** | Durable timers, retries and history for free; saga code reads like straight-line code; excellent visibility UI; SDKs for Python and Java | Another stateful cluster to run (plus its database); workflow determinism rules and versioning are a new discipline; workflow state lives outside the service DB, so "state change + outbox" atomicity needs care (activities must be idempotent and write to the outbox); the two language builds would implement and version workflows differently; it hides the saga mechanics this capstone exists to teach |
| Saga framework libraries (Axon, Eventuate Tram, MassTransit-style) | Less code | Language-specific; no single framework covers Python and Java; we would need two frameworks with two behaviours |
| Choreography only | No orchestrator | See ADR-0001 |
| AWS Step Functions / cloud workflow | Managed | Ties the template to one cloud; local development is awkward |

## Consequences

- We write and test timers, retries and compensations ourselves. The shared library provides the sweeper, the optimistic-locking repository and the transition log; each saga provides only its transition table.
- Saga state and business state sit in one database, so every transition is atomic with its outbox rows. No orchestration state can drift from the events we published.
- Visibility comes from `saga_transition` (full history per instance), the ops API, and metrics `eda_saga_*`.
- Long waits are free: a saga waiting 30 days for delivery is a row with a `deadline_at`.
- Migrating a saga's definition is a data migration: new states must handle rows in old states. Keep transitions additive and keep old states until no rows use them.

## Trade-offs

We gain transparency, one database per service, transactional consistency with the outbox, identical behaviour across languages, and no extra cluster. We pay by building timer and retry plumbing (about 300 lines per language in the shared library) and by having a less pleasant authoring model than workflow code once flows get large.

## When to revisit

Choose Temporal (option B) when one of these becomes true:

- The number of saga types grows past three or four, or a single saga passes about 15 states with branching per market or channel.
- Flows need human tasks, long sleeps with complex calendars, or child workflows.
- The platform already runs Temporal (or a similar engine) as a shared service with an on-call team.
- Teams spend more time debugging the sweeper and retries than writing business logic.
