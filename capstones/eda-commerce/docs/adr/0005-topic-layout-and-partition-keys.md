# ADR-0005: Topic layout per aggregate stream; orderId as the partition key

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0002, ADR-0004, ADR-0007, contracts/topics.yaml

## Context

We must choose how messages map to topics and how records map to partitions. Kafka orders records only within one partition. Partition count caps consumer parallelism and cannot be changed later without re-mapping keys.

The saga needs the replies about one order to arrive in the order they were produced, per participant. Read models need all events about one order in order. Catalog and stock streams are about SKUs, not orders.

## Decision

**Topic layout.**

- One **event topic per producing context**: `<context>.events.v1` (for example `payment.events.v1`). It carries every event type that context emits about the order flow, so their relative order is preserved per key.
- One **command topic per receiving service**: `<service>.commands.v1`. Only that service consumes it. Several orchestrators may produce to it.
- **Compacted state topics** for snapshot data: `catalog.product.v1`, `catalog.price.v1`, `inventory.stock-level.v1`.
- Name pattern `<context>.<stream>.v<major>`, lower case, enforced by `contracts.py validate`.

**Keys.**

- Every order-flow topic, commands included, is keyed by **`orderId`**. Returns are keyed by `orderId` too, not `returnId`, so a return's events sit in the same partition as the order's.
- State topics are keyed by **`sku`**.
- The key is copied into `envelope.partitionKey`, so it survives retry and DLQ re-publication and is visible after deserialisation.

**Partition counts.** 12 for order-flow topics (6 for low-volume ones), 6 for state topics. Twelve divides evenly across 1, 2, 3, 4, 6 and 12 consumers and leaves headroom: one partition handles far more than one shop's orders per second. All order-keyed topics use the same default partitioner (murmur2 on the key bytes) so the same orderId lands in the same partition number everywhere.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| One topic per event type (`order-placed`, `payment-authorized`, …) | Simple schemas (one per topic); consumers subscribe to exactly what they want | No ordering between e.g. `PaymentAuthorized` and `PaymentVoided` for one order; dozens of topics; every new event is a new topic and ACL |
| One topic for everything | Total per-key order across contexts | Every consumer reads everything; no per-context retention, ACLs or ownership; one bad producer hurts all |
| Key by `customerId` | All of a customer's activity ordered | Hot partitions for big B2B customers; saga replies for one order gain nothing; returns and orders interleave unnecessarily |
| Key by `returnId` for returns | Natural for the returns saga | Splits an order's lifecycle across partitions; the order-history projection would see a return before the delivery it depends on |
| Key by aggregate id per topic (reservationId, paymentId) | "Pure" aggregate ordering | Different keys for one business flow means no co-partitioning and no easy per-order reasoning; ids differ per topic |
| Many partitions (48+) "for the future" | Never need to repartition | More open files, slower rebalances, more consumer overhead; 12 is plenty for this domain |

## Consequences

- Consumers of an event topic receive types they do not care about and must skip them cheaply. They filter on the `ce_type` header before deserialising and record `outcome="ignored"`.
- Within a topic, per-order order holds. Across topics it does not. The saga handles that (architecture §5.3 rule 4).
- A very busy order (a B2B order with 10,000 lines) cannot be parallelised. That is acceptable: one order's events are few.
- Consumer groups cannot usefully scale beyond 12 instances. The KEDA scaler is capped at 12.
- Changing a partition count is a migration: create a `.v2` topic with the new count and dual-publish, exactly like a breaking schema change.

## Trade-offs

We gain per-order ordering within each context's stream, co-partitioned topics, a manageable number of topics and clear ownership. We pay with consumers filtering out irrelevant types and with no ordering across contexts, which every orchestrator must design for.

## When to revisit

- A single context's event topic carries more than about 20 types and most consumers skip most of them: split by sub-domain.
- Measured per-partition throughput approaches 25 % of a partition's capacity at peak: plan a `.v2` with more partitions.
- A multi-tenant reuse of the template needs tenant isolation: consider `tenantId:orderId` keys or per-tenant topics.
