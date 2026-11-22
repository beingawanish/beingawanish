# ADR-0001: Hybrid integration: orchestrate compensating flows, choreograph the rest

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0008 (saga implementation), ADR-0015 (capture at dispatch), docs/architecture.md §4

## Context

An order touches seven services. Some steps move money or stock and must be undone if a later step fails. Others are simple hand-offs or side effects: send an email, update a read model, book a label after packing.

There are two pure styles. In **choreography**, each service reacts to the events of others and nobody holds the overall picture. In **orchestration**, one service holds the state of the flow, sends commands, and decides what happens on each reply.

Pure choreography looks decoupled on a whiteboard. In practice the flow logic is smeared across services. "What happens when payment is declined after stock was reserved?" has no single answer location. Compensation chains become implicit and fragile, and a new rule ("cancel if the warehouse has not accepted in 30 minutes") needs coordinated changes in three codebases.

Pure orchestration makes every interaction a command. The orchestrator then knows about emails, read models and label printing. It becomes a god service, and every new listener means an orchestrator change.

## Decision

We will use **orchestration** for flows that need compensation or a single decision-maker:

- the order saga in order-svc (stock, payment, fulfilment request, capture), and
- the returns saga in returns-svc (label, inspection, restock, refund).

We will use **choreography** for linear hand-offs and pure reactions:

- fulfilment ↔ shipping (packed → label booked → dispatched),
- notification, order-history projection, checkout cart closure, catalog availability.

Orchestrators talk to participants with **commands on the participant's command topic** and receive **replies as events on the participant's event topic**. Participants never know who orchestrates them. A reply is an ordinary event that anyone may consume.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Pure choreography | No central component; services evolve independently; fewer messages | No single place owns the flow; compensation is implicit; timeouts ("nothing happened for 10 minutes") have no natural home; hard to answer "where is order X stuck?" |
| Pure orchestration | One place for all logic; easy to visualise | Orchestrator couples to every side effect; adding a listener means changing the orchestrator; it becomes the bottleneck for change |
| Orchestration via synchronous HTTP calls | Simple to code, easy to debug | Temporal coupling: if payment-svc is down, checkout fails; retries and timeouts become each caller's problem; no replay |

## Consequences

- order-svc and returns-svc contain explicit state machines, deadlines and compensation logic (ADR-0008). They are the most complex services and get the most tests.
- Participant services stay simple: consume a command, do the work, publish a reply.
- A reply event can trigger both the orchestrator and listeners. `PaymentAuthorized` drives the saga and also the order timeline.
- Everyone needs to know which style applies where. docs/architecture.md §4 is the reference, and code review enforces it.

## Trade-offs

We gain one place to read, test and monitor each business flow, with explicit timeouts and compensations. We pay with more messages (a command plus a reply instead of one event) and with an orchestrator that is a real piece of software, not glue. We also accept that the fulfilment ↔ shipping hand-off is invisible to the saga until `OrderDispatched`; the saga only watches its deadline.

## When to revisit

- A choreographed segment grows a compensation need (for example "if label booking fails three times, cancel the order"). Move it under the orchestrator.
- The orchestrator's state machine passes about 15 states or gets branches per country or channel. Consider splitting into sub-sagas or moving to a workflow engine (ADR-0008 option B).
- Teams report that adding a listener requires orchestrator changes. That means commands are being used where events belong.
