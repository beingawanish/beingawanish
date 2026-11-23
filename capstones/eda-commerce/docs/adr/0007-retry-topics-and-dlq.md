# ADR-0007: Blocking retry for transient errors, retry topics for slow recovery, a DLQ per consumer group

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0005, ADR-0006, contracts/topics.yaml (retryPolicy), contracts/openapi/admin.yaml (/ops/dlq)

## Context

Handlers fail for different reasons, and each reason wants a different response:

- **Transient infrastructure errors** (database failover, a 503 from object storage) usually clear in seconds.
- **Slow dependencies** (the PSP is degraded for ten minutes) clear in minutes.
- **Poison messages** (cannot deserialise, violates an invariant, a bug) never clear by waiting.

Kafka has no built-in delayed redelivery or dead-lettering. If a consumer simply retries in place forever, one poison message blocks its whole partition: every order behind it stalls. If it skips failures, data is lost.

## Decision

The shared consumer library implements three tiers.

1. **In-place retry** for errors classified as transient: up to 5 attempts with exponential backoff and jitter (200 ms → 3.2 s), on the same thread, without committing. The partition is paused while waiting, so the consumer keeps its group membership.
2. **Non-blocking retry topics** when in-place retries are exhausted, or immediately for errors classified as "retry later": the record is forwarded to `<group>.retry.10s`, then `<group>.retry.1m`, then `<group>.retry.10m`. The original offset is committed, so the partition moves on. Each retry consumer waits until the `x-not-before` header time, then calls the **same handler**.
3. **Dead-letter topic** `<group>.dlq` when all retries are exhausted, or immediately for non-retryable errors (deserialisation failure, schema not found, validation error, unknown enum where the handler cannot default). DLQ entries raise an alert and are replayed only by a human through `POST /ops/dlq/replay`, which re-publishes into `<group>.retry.10s`.

Rules:

- Retry and DLQ topics are **per consumer group**, not per source topic. A replay affects only the group that failed. Other groups that processed the message are untouched.
- Forwarding copies the **original key and value bytes unchanged** and adds headers (`x-retry-attempt`, `x-original-topic`, `x-original-partition`, `x-original-offset`, `x-not-before`, `x-error-class`, `x-error-message`, `x-failed-consumer-group`). It never re-serialises, so no extra schema subjects exist for these topics.
- Error classification is explicit in code: each adapter maps its exceptions to `Transient`, `RetryLater` or `NonRetryable`. Unknown exceptions count as `RetryLater`.
- Retry topics break per-key ordering for the retried message. That is safe here because every handler is guarded: orchestrators check saga state and business ids, read models check `aggregateVersion`, participants check business ids (ADR-0006).

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Retry in place forever | Preserves strict ordering | One poison message stops the partition; the outage spreads to every order in it |
| Skip and log | Never blocks | Silent data loss |
| Retry topics per source topic (Spring's default naming `<topic>-retry-N`) | Built into Spring Kafka `@RetryableTopic` | Shared by every group that consumes the topic; a replay re-delivers to all of them; naming differs from Python |
| Keyed parking ("once a key fails, park all later messages for that key") | Preserves per-key order even under retry | Complex state per key; worth it only for consumers that cannot tolerate reordering, and ours can |
| Broker with native delays (RabbitMQ DLX + TTL) | Less code | See ADR-0002 |
| Retry state in the database instead of topics | Precise scheduling | Mixes message transport into the business DB; replay tooling must be custom anyway |

## Consequences

- 40 extra topics (10 groups × 4). Generated from `topics.yaml`, created by `make topics`.
- Each service runs a retry consumer for its own retry topics, from the same library, with a separate consumer group id suffix (`<group>-retry`).
- Java: implement with Spring Kafka's `DefaultErrorHandler` + `DeadLetterPublishingRecoverer` and a destination resolver that produces our names, not with `@RetryableTopic`'s default naming. Python: implemented directly on confluent-kafka in the shared library. Both must produce identical headers.
- The DLQ is an operational queue with an owner, an alert and a runbook (architecture §12), not a graveyard.

## Trade-offs

We gain partitions that never block on a single bad message, bounded and observable retries, and safe targeted replay. We pay with more topics, a second consumer per service, possible reordering of retried messages, and the requirement that every handler is order-tolerant.

## When to revisit

- A consumer appears that truly needs strict per-key order under failure (for example a ledger posting). Give that consumer keyed parking or in-place-only retry plus an alert.
- Retry volume is a large share of traffic. The classification is wrong or a dependency is unhealthy; fix the cause, not the delays.
