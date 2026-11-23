# inventory-svc (port 8105)

Stock per SKU, reservations with a TTL, commits after payment authorisation, releases as compensation, restocks for returns (ADR-0016).

**Owns:** `stock`, `reservation`, `reservation_line`, `restock` (`V2__inventory.sql`) plus the shared tables.
**Consumes:** `inventory.commands.v1` (ReserveStock, CommitReservation, ReleaseReservation, RestockItems). **Publishes:** `inventory.events.v1` (StockReserved, StockReservationRejected, ReservationCommitted, ReservationReleased, ReservationExpired, ItemsRestocked; key orderId), `inventory.stock-level.v1` (StockLevelChanged; key sku, version = stock row version).
**HTTP:** `PUT /admin/stock/{sku}` (admin.yaml), `/ops/dlq`, `/health/*`.
**Config:** `RESERVATION_TTL` (900s), `RESERVATION_SWEEP_INTERVAL` (5s).

**Patterns:** participant of the order saga, idempotent on business ids (`reservationId`, `restockId`): a resend re-emits the original reply; inbox for message-level duplicates; TTL sweeper with `FOR UPDATE SKIP LOCKED`; outbox for replies and stock snapshots. The domain (`Reservation`, `Restock`) decides; the persistence adapter applies `StockEffect`s with conditional updates.

## Decisions and trade-offs

- **Row locks in SKU order, then conditional updates.** All-or-nothing without savepoints, deadlock-free across orders, and the `on_hand - reserved >= q` condition stays as a guard (architecture §9). Cost: buyers of one hot SKU serialise on its row (ADR-0016 "when to revisit").
- **The TTL is the command's, capped by RESERVATION_TTL.** order-svc sends 900 s; the §5.7 drill shortens the TTL on inventory-svc alone.
- **A release before the reserve leaves a RELEASED tombstone,** so a late ReserveStock with the same id does nothing (it answers ReservationReleased). Releasing an expired or rejected reservation confirms the compensation without touching stock.
- **A commit after the TTL answers ReservationExpired,** even if the sweeper has not run yet.
- **Stock rows via JdbcTemplate, reservations via JPA** in one transaction: the hot path reads best as SQL.
