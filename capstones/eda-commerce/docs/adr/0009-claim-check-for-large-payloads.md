# ADR-0009: Claim check in object storage for large payloads

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0003, ADR-0013, contracts/avro/common/ClaimCheck.avsc, docs/architecture.md §7

## Context

Some business artefacts are big: invoice PDFs (50–200 KB), packing manifests with per-item scans, lot and serial numbers (up to several MB for B2B orders), shipping labels. Kafka's default maximum message size is 1 MB. Raising it hurts broker memory, replication and consumer latency for everyone. Large values in the outbox also bloat the WAL and Debezium's throughput. And invoices are legal documents with retention rules that have nothing to do with topic retention.

## Decision

Payloads above **256 KB**, and every binary document regardless of size, travel by **claim check**:

1. The producer computes the bytes and their SHA-256.
2. It uploads to object storage (MinIO locally, S3-compatible in production) **before** its database transaction. The object key is **deterministic from business ids** (`<context>/<yyyy>/<mm>/<aggregateId>/<documentId>.<ext>`), so a retry overwrites the same object instead of creating a new one.
3. In the transaction it writes the outbox row with a `ClaimCheck{store, bucket, objectKey, contentType, sizeBytes, sha256, expiresAt}` field.
4. Consumers download, verify the hash and size, then process. A missing object is a `RetryLater` error for 10 minutes, then DLQ.
5. Humans and emails get **pre-signed URLs** valid for 5 minutes (`GET /orders/{id}/invoice` answers 302). Services never stream documents through their APIs.

Buckets have lifecycle rules per document type (`infra/minio/init.sh`): invoices are kept (versioned; object lock in production), manifests 90 days, labels 30 days, temporary notification attachments 2 days.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Raise `max.message.bytes` to 10 MB | No extra component | Every broker, consumer and replica pays; one huge message delays the partition; still capped |
| Chunk large messages across records | Stays in Kafka | Reassembly, ordering and partial-failure logic in every consumer; terrible to debug |
| Store blobs in the producer's database, expose via API | One storage system | Consumers call the producer synchronously; producer DB grows with binaries; couples availability |
| Base64 in Avro `bytes` under 1 MB | Simple | 33 % overhead; still too big for manifests; documents with legal retention would expire with the topic |

## Consequences

- Object storage is on the critical path of three producers. If it is down, those producers retry and the business step waits (the `chaos-minio` drill). Nothing is published that points at a missing object.
- Orphan objects are possible (upload succeeded, transaction rolled back). Lifecycle rules remove them; for invoices, a weekly job compares objects against `invoice` rows.
- Consumers need read access to the producer's bucket. Locally one key pair; in production one identity per service with bucket policies: producer writes, named consumers read.
- The claim check carries `sha256`, so a tampered or truncated object is detected.
- Replaying an old event after its object expired yields a missing object. Consumers treat an expired `expiresAt` as "skip with a warning", not as an error.

## Trade-offs

We gain small, fast Kafka messages, document retention decoupled from topic retention, and direct, secure document access for customers. We pay with another dependency on the write path, orphan cleanup, and access control on buckets.

## When to revisit

- Payloads are all small after all (below 100 KB): inline them and drop the dependency for that event.
- A document management system becomes the system of record for invoices: the claim check then points at it (`store` field supports other schemes).
