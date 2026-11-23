# inventory-svc (Python)

Holds stock per SKU and reservations with a TTL. It reserves before payment, commits after authorisation and releases as a compensation (ADR-0016). Port 8105, consumer group `inventory-svc`.

## Owns

`stock` (on_hand, reserved, version), `reservation` (+ `reservation_line`), `restock`, plus the shared `outbox`, `inbox` and `idempotency_key`.

## Topics and APIs

| | |
|---|---|
| Consumes | `inventory.commands.v1`: ReserveStock, CommitReservation, ReleaseReservation, RestockItems |
| Publishes | `inventory.events.v1`: StockReserved, StockReservationRejected, ReservationCommitted, ReservationReleased, ReservationExpired, ItemsRestocked. `inventory.stock-level.v1` (compacted, key sku): StockLevelChanged after every stock change |
| HTTP | `PUT /admin/stock/{sku}` (seed), `/ops/dlq`, `/ops/dlq/replay`, `/health/*` |
| Config | `RESERVATION_TTL` (900s), `RESERVATION_SWEEP_INTERVAL` (5s), plus guide §7 |

## Stock rules

| Operation | Effect |
|---|---|
| reserve (HELD) | `reserved += q` |
| commit | `on_hand -= q; reserved -= q` (allocated to the order) |
| release HELD | `reserved -= q` |
| release COMMITTED | `on_hand += q` |
| expire | `reserved -= q` |
| restock | `on_hand += q` |

## Patterns used

Inbox and idempotent business ids (a resend with the same `reservationId` re-emits the *original* reply), transactional outbox, a conditional update for the stock invariant, a TTL sweeper with `FOR UPDATE SKIP LOCKED`, and compacted state snapshots.

## Decisions and trade-offs

- **Conditional update, not row locks in application code** (architecture §9). `UPDATE stock SET reserved = reserved + :q WHERE sku = :s AND on_hand - reserved >= :q` keeps stock from going negative under any concurrency; the last-unit race test proves it. All-or-nothing reservations use a SAVEPOINT, and lines are locked in SKU order so two reservations never deadlock. The cost: on a shortage the savepoint rollback costs one extra read to report the available quantities.
- **Release tombstones.** A `ReleaseReservation` for an unknown id writes a `RELEASED` row and replies `ReservationReleased`, so a late `ReserveStock` (delivered through a retry topic) can never hold stock for a cancelled order. The cost: one extra row per lost reservation.
- **Commit after TTL answers `ReservationExpired`**, even if the sweeper has not run yet (ADR-0016). The saga then cancels and voids (architecture §5.7).
- **TTL = min(command `ttlSeconds`, `RESERVATION_TTL`).** The service caps holds, which is how the expiry drill runs at 60 s. That is a choice of this build; see the top-level README.
- **Stock levels are published on every change, inside the same transaction.** That costs one more outbox row per change, and buys product pages that converge within the relay latency. The levels are advisory; only the reservation counts.
