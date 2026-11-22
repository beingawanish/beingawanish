# ADR-0006: Idempotent consumers with an inbox table and idempotent business ids

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0003, ADR-0007, ADR-0012, contracts/sql/common-tables.sql

## Context

Every path in this system delivers at least once. Debezium can re-publish after a restart. A consumer can crash after its database commit and before its offset commit. A rebalance can hand a partition to another instance mid-batch. The PSP and the carrier retry webhooks until they see a 2xx and sometimes send duplicates on purpose. Orchestrators resend commands after deadlines.

Processing a duplicate must have no visible effect. Charging a card twice, reserving stock twice or sending two "your order shipped" emails are all real incidents in real shops.

## Decision

Three layers, each cheap:

1. **Inbox table per service.** In the same transaction as the handler's business change, insert `(message_id = envelope.eventId, consumer = group)` into `inbox`. A primary-key conflict means "already processed": roll back the empty transaction, record `outcome="duplicate"`, commit the offset, move on. Webhooks use the provider's event id and `consumer = 'psp-webhook'` or `'carrier-webhook'`.
2. **Idempotent business ids on commands.** Orchestrators mint `reservationId`, `paymentId`, `fulfilmentId`, `refundId`, `shipmentId` once and reuse them on every resend. A resend has a **new** `eventId` (so it passes the inbox) but the **same** business id, and the participant treats "I already did this business operation" as success and re-emits its original reply. This is what makes resends safe, and it is the part people forget.
3. **External idempotency keys.** payment-svc passes `paymentId` / `refundId` as the PSP's idempotency key. The PSP then guarantees one charge per key even if our own records are lost.

**Commit order** for a consumer: process + inbox insert + outbox rows in one DB transaction → commit DB → commit Kafka offset. Never the other way round.

**Housekeeping.** Inbox rows older than 100 days are deleted (longest topic retention 90 days, plus margin). Older duplicates cannot arrive.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Kafka exactly-once (transactions, read_committed) | Built into Kafka | Only covers Kafka-to-Kafka; our side effects are in Postgres and at the PSP |
| Naturally idempotent handlers only ("set status to X") | No table | Holds for some handlers, not for "reserve 2 units" or "send email"; easy to break in a later change |
| Dedupe cache in Redis with TTL | Fast; shared across services | Not in the same transaction as the business change, so a crash between them still duplicates; another component to run |
| Dedupe on business id only | One mechanism | Fine for commands, but events without a natural business id (notifications, read model updates) still need message-level dedupe |
| Store last processed offset per partition in the DB | Exactly-once with one row per partition | Breaks under retry topics and replays; ties correctness to offsets, which change on topic migration |

## Consequences

- Every handler runs inside a unit of work provided by the shared library. Handlers that bypass it are a review blocker.
- Participants need a lookup "have I seen this business id?" (for example `payment WHERE payment_id = ?`), and must return the **original** result, not an error.
- The inbox grows with traffic. An index on `received_at` and a daily delete keep it bounded.
- Read-model handlers additionally guard on `aggregateVersion` (drop if not newer), which also makes them safe under replay and reordering.

## Trade-offs

We gain effectively-once business effects on top of at-least-once delivery, with no extra infrastructure and no distributed transaction. We pay with one insert per message, an extra table per service, and a discipline (stable business ids) that must be taught and reviewed.

## When to revisit

- Inbox inserts show up as a bottleneck (thousands of messages per second per service): partition the table by day, or batch inserts per poll.
- A consumer has no database (a pure forwarder): it must be stateless and naturally idempotent, or it needs a database.
