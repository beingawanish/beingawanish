# ADR-0016: Inventory reservations with a TTL, committed after authorisation

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0008, ADR-0015, docs/architecture.md §5.7, §9

## Context

Two customers can try to buy the last unit at the same moment (SKU-1005 in the seed data). Payment can take seconds or, in the PSP timeout path, minutes. If we take money first and check stock second, we refund people for items we never had. If we decrement stock at the start and the order dies (the saga crashes, the customer's card hangs), the unit is locked away forever.

## Decision

- **Reserve before paying.** The order saga's first command is `ReserveStock`. inventory-svc reserves all lines or none, using a conditional update per SKU so stock can never go negative.
- **Every reservation has a TTL** (default 900 s, set per command). A sweeper in inventory-svc (`FOR UPDATE SKIP LOCKED`, every 5 s) expires overdue reservations, returns the units to the pool and emits `ReservationExpired`.
- **Commit after authorisation.** `CommitReservation` turns the hold into an allocation with no TTL. A commit that arrives after expiry is answered with `ReservationExpired`, and the saga cancels and voids (architecture §5.7).
- **Release is the compensation** for both held and committed reservations. Releasing twice is a no-op.
- **Stock levels are published** on the compacted `inventory.stock-level.v1` after each change, for product pages and cart hints. They are advisory; only the reservation is authoritative.
- **Restock** (returns) adds inspected, sellable units back with its own idempotent `restockId`.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Decrement at payment success | No reservations to expire | Oversell under concurrency; refunds for phantom stock |
| Reserve without TTL; release only by saga compensation | Simpler inventory | A lost saga (bug, data loss) locks stock forever; the TTL is a safety net independent of the orchestrator |
| Re-reserve on expiry instead of cancelling | Saves some orders | The second reservation can fail too; adds a third outcome to explain to the customer; revisit if expiries are common |
| Distributed lock per SKU (Redis) | Fast | Another component; the database conditional update is correct and fast enough |

## Consequences

- Two timers exist for one order: the saga's step deadline and the reservation TTL. They are independent on purpose. The TTL (900 s) is longer than the payment step deadline (180 s) plus one resend, so the race in §5.7 happens only on the slow PSP path.
- Reserved stock is unavailable to other customers for up to 15 minutes even if the first customer abandons. That is the price of not overselling.
- Inventory is the hot spot under flash sales. A conditional update per SKU row serialises buyers of one SKU, which is correct but limits throughput for a single hot item to the row's update rate.

## Trade-offs

We gain no overselling, no stock locked forever, and an inventory service that protects itself regardless of orchestrator health. We pay with a sweeper, a race between TTL and slow payments that the saga must handle, and temporarily hidden stock.

## When to revisit

- Flash sales with thousands of buyers per SKU per second: shard stock per SKU into buckets, or move to a queue-based allocation for that SKU.
- Expiry-driven cancellations exceed 1 % of orders: lengthen the TTL or re-reserve.
- Multi-warehouse allocation is required: reservations gain a warehouse dimension and the stock-level topic becomes per warehouse.
