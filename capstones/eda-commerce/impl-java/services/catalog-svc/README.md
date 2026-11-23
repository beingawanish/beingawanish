# catalog-svc (port 8101)

Products and prices, the browse API, full snapshots on compacted topics, and a projection of stock levels.

**Owns:** `product`, `price`, `stock_level_view` (`V2__catalog.sql`).
**Consumes:** `inventory.stock-level.v1`. **Publishes:** `catalog.product.v1` ProductUpserted (key sku, version = product version), `catalog.price.v1` PriceChanged (key sku, version = price version; only when the price changed).
**HTTP:** `GET /products` (category, q, cursor, limit; active products only), `GET /products/{sku}` (ETag), `PUT /admin/products/{sku}` (used by `infra/scripts/seed.sh`).

**Patterns:** published language on compacted topics (each record is the whole truth, consumers rebuild from offset 0); outbox; version-guarded projection.

## Decisions and trade-offs

- **Every upsert republishes the product snapshot** (version + 1) even when nothing changed: idempotent for consumers, and the seed script can be re-run.
- **One price list (`retail-eu`).** The contract allows several; this build does not need them yet.
- **Availability thresholds** (LOW_STOCK at 5 or fewer) are a template rule in `domain/Availability`.
- **Null optional fields are omitted from JSON** (guide §5 rule 10), which also keeps the OpenAPI validator happy with `oneOf [Money, null]`.
