# checkout-svc (port 8102)

Carts priced from a local catalog read model, and checkout submission. Mints the orderId.

**Owns:** `cart`, `cart_line`, `checkout`, `catalog_view` (`V2__checkout.sql`), `idempotency_key`.
**Consumes:** `catalog.product.v1`, `catalog.price.v1`, `inventory.stock-level.v1` (into `catalog_view`), `order.events.v1` (OrderPlaced/OrderCancelled mark the checkout row). **Publishes:** `checkout.events.v1` CheckoutSubmitted (key orderId, aggregate Checkout/checkoutId, correlation orderId).
**HTTP:** `POST /carts` (Idempotency-Key), `GET /carts/{id}`, `PUT/DELETE /carts/{id}/items/{sku}` (ETag, If-Match -> 412), `POST /checkouts` (Idempotency-Key, 202 + Location, 409/422).

**Patterns:** CQRS read model of three compacted topics, each part version-guarded (ADR-0010); `expectedTotal` reread check (422 `price-mismatch`); Idempotency-Key via edacommon (ADR-0012); outbox in the same transaction as the checkout row and the key.

## Decisions and trade-offs

- **Prices are tax-inclusive (EU), VAT 19 % included per line with banker's rounding; shipping STANDARD 4.99 (free from 50.00), EXPRESS 9.99.** These are template business rules, not contract; change them in `domain/Pricing`.
- **Availability is advisory:** a cart may not exceed the last known availability, but only the inventory reservation is authoritative.
- **`pricedAt` is the oldest read-model row used,** so the client sees how fresh the prices are.
- **A cart that cannot be checked out answers 422** (`cart-not-found`, `cart-empty`, `cart-already-checked-out`, `discontinued-sku`, `price-mismatch`), as checkout.yaml lists only 422 for these.
- **Persistence via JdbcTemplate:** the read model is conditional upserts; carts are small. JPA is used in inventory, payment and order.
