# ADR-0002: Kafka, not RabbitMQ, as the event backbone

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0003, ADR-0005, ADR-0007, ADR-0010

## Context

The services need a broker for commands, replies and domain events. Requirements:

- Several independent consumers per event stream (saga, read model, notifications, returns), added over time without changing producers.
- Replay: rebuild a read model or a new consumer from history.
- Per-order ordering for saga replies.
- Compacted "latest state" streams for catalog and stock levels.
- A mature CDC path from Postgres (ADR-0003).
- Throughput is moderate (hundreds of orders per second at peak in a real shop), so raw speed is not the deciding factor.

## Decision

We will use **Apache Kafka in KRaft mode** (no ZooKeeper) with Confluent Schema Registry. Locally a single combined broker/controller; in production at least three brokers, replication factor 3, `min.insync.replicas=2`, producers with `acks=all` and idempotence on.

Commands also travel over Kafka, on one topic per receiving service (`<service>.commands.v1`). We do not run a second broker for commands.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| RabbitMQ (classic or quorum queues) | Excellent for work queues and commands; per-message acks, TTL, delayed delivery and DLX built in; simple to operate; flexible routing | Messages disappear once consumed, so no replay and no new consumer from history; per-key ordering needs one queue per consumer plus consistent-hash exchange; no compaction |
| RabbitMQ Streams | Adds a replayable log to RabbitMQ | Younger ecosystem; weaker client support in our two languages; Debezium and Kafka Connect tooling do not apply |
| Kafka for events + RabbitMQ for commands | Each tool where it shines | Two brokers to run, secure and monitor; two client libraries per language; the outbox relay must target both |
| Managed cloud queues (SQS/SNS, Pub/Sub) | No operations | Locks the template to one cloud; ordering and replay semantics differ per vendor; the capstone must run on a laptop |
| Apache Pulsar | Log + queue semantics in one; tiered storage | Smaller ecosystem; heavier to run locally; fewer engineers know it |

## Consequences

- Retry with delay and dead-lettering are not built into Kafka. We build them (ADR-0007).
- Consumers track offsets. Exactly-once processing is our job (ADR-0006).
- Partition counts are fixed at creation and decide the maximum consumer parallelism (ADR-0005).
- Operating Kafka well requires skills: partition planning, rebalance tuning, lag monitoring. The template includes lag dashboards and alerts from day one.

## Trade-offs

We gain a durable, replayable, ordered log that many consumers share, and the Connect/Debezium ecosystem. We pay with more work for per-message concerns (delayed retry, DLQ) that RabbitMQ gives for free, and with heavier operations. For a shop that only needs task queues between two services, RabbitMQ would be simpler and better.

## When to revisit

- The system turns into mostly point-to-point work queues with no replay needs. RabbitMQ (or a managed queue) is then the simpler choice.
- Delayed and scheduled delivery becomes central (for example many per-message timers). Consider a broker with native delays, or keep timers in the database as we do for sagas.
- The organisation standardises on a managed streaming service. The contracts and the outbox stay the same; only adapters change.
