# ADR-0003: Transactional outbox relayed by Debezium CDC

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0002, ADR-0006, contracts/sql/common-tables.sql, infra/connect/connectors/

## Context

Every interesting state change must produce an event. The change lives in Postgres, the event in Kafka. These are two systems with no shared transaction. If a service writes the row and then publishes, a crash in between loses the event. If it publishes first and the database commit fails, the world hears about something that never happened. This is the dual-write problem, and under load it is not rare.

## Decision

We will use the **transactional outbox** pattern. Each service writes its business change and one or more rows in its own `outbox` table **in the same database transaction**. A relay publishes outbox rows to Kafka afterwards.

The relay is **Debezium** (Postgres connector, `pgoutput` plugin) running in Kafka Connect, one connector per service database, with the **Outbox Event Router** transform:

- The Kafka topic comes from the `topic` column, the key from `aggregate_id`, the value from `payload`.
- `payload` already holds Confluent-wire-format Avro bytes, serialised by the service. Debezium's `BinaryDataConverter` passes the bytes through untouched. The relay never re-encodes.
- Envelope fields (`ce_id`, `ce_type`, `ce_source`, `ce_time`, correlation, causation, trace context) are copied to Kafka headers.
- `snapshot.mode=initial`: a newly created connector also publishes rows already in the table. Duplicates are cheap (the inbox absorbs them, ADR-0006); a lost event is not.
- The service's own migration creates the table and the `outbox_pub` publication. The connector runs as a least-privilege `debezium` role with `REPLICATION` and `SELECT` on `outbox` only.

Every service also ships a **polling relay** (`OUTBOX_RELAY=polling`) in its shared library. It is the fallback for environments without Connect and for fast integration tests. It uses `SELECT … FOR UPDATE SKIP LOCKED` in insertion order and marks `published_at`.

Outbox rows are kept for 7 days and then deleted by a housekeeping job.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Dual write (commit, then produce) | Simplest code; no extra infrastructure | Loses events on crash between the two steps; produces phantom events if produce-then-commit; impossible to make correct |
| Kafka transactions | Exactly-once inside Kafka | Cannot include the Postgres commit; does not solve dual write |
| Polling relay as the default | No Connect cluster; easy to understand and test | Polling interval adds latency (or load if short); ordering across relay replicas needs care; the table becomes a hot queue; must be built and tuned per language |
| Debezium without the outbox (raw table CDC) | No outbox table at all | Publishes internal table structure as the public contract; schema changes break consumers; no control over event shape |
| Event sourcing (events are the source of truth) | No dual write by construction; full history | Big shift in programming model for every service; queries need projections everywhere; overkill for most of these contexts |
| Listen/notify + in-process publisher | Low latency | Notifications are lost when nobody listens; still needs a polling safety net |

## Consequences

- Publishing is **at-least-once**. A connector restart can re-send recent rows. Every consumer must be idempotent (ADR-0006).
- Event latency is WAL-driven: typically tens of milliseconds, part of the event-age SLO.
- Kafka Connect is a critical component. If it stops, writes still succeed and events queue in the outbox (the `chaos-connect` drill proves it). It must be monitored: connector state and replication-slot lag.
- A stuck replication slot retains WAL. `max_slot_wal_keep_size=2GB` caps the damage: the slot is invalidated instead of filling the disk, and the connector must be re-created (with `snapshot.mode=initial`, it then re-publishes the retained outbox rows).
- Producing services need the Schema Registry to serialise, at write time, inside the business transaction. A cold cache with the registry down fails the write (ADR-0004 covers caching).
- One connector and one replication slot per service database. Nine slots locally.

## Trade-offs

We gain atomic "state change + event", ordered per aggregate, with low latency and no polling load. We pay with Kafka Connect as extra infrastructure, Debezium expertise, replication-slot hygiene and at-least-once semantics that every consumer must handle.

## When to revisit

- The platform has no Connect cluster and does not want one: make the polling relay the default; nothing else changes.
- A service moves to a database Debezium does not support well: use the polling relay for that service.
- A context's history becomes the product (audit-heavy domains such as ledgers): consider event sourcing for that context only.
- Debezium's outbox router gains native support for schema-registry-encoded payloads with header mapping in a different way: simplify the connector config.
