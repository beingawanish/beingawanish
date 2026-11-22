# ADR-0010: CQRS read models for catalog-at-checkout and order history

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** ADR-0005, ADR-0006, contracts/openapi/orders.yaml, docs/architecture.md §9

## Context

Two read paths are hot and cross-context:

1. **Pricing a cart.** checkout-svc needs product names, status, prices and approximate availability for every cart view and every checkout. Calling catalog-svc and inventory-svc synchronously makes checkout's availability the product of three services' availability, and adds two network hops to the most important request in the shop.
2. **Order status and history.** The customer's view of an order combines the order saga, payment, fulfilment, shipping, returns and notifications. The saga table is shaped for transitions, not for "show me my last 20 orders with tracking numbers".

## Decision

**Catalog read model in checkout-svc.** checkout-svc consumes the compacted topics `catalog.product.v1`, `catalog.price.v1` and `inventory.stock-level.v1` from offset 0 into its own `catalog_view` table. Carts are priced from it. Each snapshot record replaces the row if its `aggregateVersion` is newer. The cart API reports `pricedAt` (read-model freshness). At checkout the client sends `expectedTotal`; a mismatch returns 422, so a stale view can never charge a surprise amount. Availability is advisory; the inventory reservation is the real check.

**Order-history read model.** A separate process from the order-svc codebase, consumer group `order-history-projector`, builds the `order_history` schema in `order_db` (an order summary row, line rows, a timeline table) from `order.events.v1`, `payment.events.v1`, `fulfilment.events.v1`, `shipping.events.v1`, `returns.events.v1` and `notification.events.v1`. order-svc serves `GET /orders/{id}` and `GET /customers/me/orders` from it. For a single order not yet projected, order-svc falls back to its saga table and marks `source: WRITE_MODEL_FALLBACK`.

**Rebuilds.** A read model is disposable. To rebuild: create a new schema (`order_history_v2`), run a projector with a new group id from the earliest offset, switch reads, drop the old schema. Topic retention (90 days for orders and returns) bounds what a rebuild can see. Older orders are back-filled once from order-svc's own tables via a one-off export job that emits the same projection rows.

## Alternatives considered

| Option | Why it is attractive | Why we did not pick it |
|---|---|---|
| Synchronous calls to catalog and inventory at checkout | Always fresh | Availability multiplies down; latency adds up; catalog traffic spikes with checkout traffic |
| Shared read replica of catalog's database | Fresh, no projection code | Couples schemas across teams; a catalog migration breaks checkout |
| Query the saga table for order history | No extra process | Saga table lacks shipment, refunds and notifications; joins across contexts would need API calls |
| API composition (gateway calls all services per request) | No duplication | Slow, fragile, N calls per page |
| Infinite topic retention as the rebuild source | Simple rebuilds forever | Storage cost; personal data in old events conflicts with erasure (ADR-0013) |

## Consequences

- Readers see slightly stale data. The staleness is measured (event age of the projector, SLO p99 < 2 s) and shown to clients (`pricedAt`, `version`).
- Projection handlers must be idempotent and order-tolerant: drop any update whose `aggregateVersion` is not newer for that row; timeline rows are keyed by `eventId`.
- Every new field in the order view needs a projection change and, for old orders, a backfill.
- The projector can lag without affecting the saga, because it is a different consumer group and a different process.

## Trade-offs

We gain fast, available reads that do not depend on other services at request time, shaped exactly for the UI. We pay with eventual consistency, projection code, extra storage and rebuild procedures.

## When to revisit

- Search requirements appear (facets, full text): project the catalog into a search engine instead of a table.
- Read-model staleness causes support tickets: tighten the SLO or add read-your-writes fallbacks for more endpoints.
- The order view becomes a product of its own (customer service console with many filters): give it its own service and store.
