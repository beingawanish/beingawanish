# catalog-svc (Python)

Holds product master data and prices. It serves the browse API and publishes full snapshots on compacted topics. Port 8101, consumer group `catalog-svc`.

## Owns

`product`, `price`, `stock_level_view`, plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Publishes | `catalog.product.v1` (ProductUpserted), `catalog.price.v1` (PriceChanged): both compacted and keyed by sku, with `aggregateVersion` = product version |
| Consumes | `inventory.stock-level.v1` (StockLevelChanged) into `stock_level_view` |
| HTTP | `GET /products` (category, q, cursor, limit; ACTIVE only), `GET /products/{sku}` (ETag), `PUT /admin/products/{sku}` (ops), `/ops/dlq*` |

## Decisions and trade-offs

- **Snapshots, not deltas** (ADR-0010, architecture §8.2). Every change publishes the whole product or price, so a consumer that reads from offset 0 rebuilds the full catalogue. An unchanged write publishes nothing, which makes the seed script idempotent. A price-only change publishes only `PriceChanged`.
- **One version per product, shared by both snapshots.** Consumers keep separate version columns per snapshot type, so they never compare a price version with a product version. This is simple; the cost is that the price topic's versions have gaps.
- **Availability is advisory.** It is projected from inventory's compacted topic, and only a strictly newer `aggregateVersion` replaces the row. The bands are UNKNOWN, OUT_OF_STOCK, LOW_STOCK (≤ 5) and IN_STOCK.
- **Cursor = last SKU.** Paging is stable and cheap. The cursor is only semi-opaque; switch to an encoded cursor if the sort order ever changes.
