# checkout-svc (Python)

Holds carts, prices them from a local catalog read model, and submits checkouts. It **mints the orderId** and starts the order saga with `CheckoutSubmitted`. Port 8102, consumer group `checkout-svc`.

## Owns

`cart`, `cart_line`, `checkout`, `catalog_view`, `idempotency_key`, plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Consumes | `catalog.product.v1`, `catalog.price.v1`, `inventory.stock-level.v1` (into `catalog_view`, from offset 0); `order.events.v1` (OrderPlaced, OrderConfirmed, OrderCancelled update `checkout.order_status`) |
| Publishes | `checkout.events.v1`: CheckoutSubmitted (key orderId, PII-tagged address and email) |
| HTTP | `POST /carts` (Idempotency-Key), `GET /carts/{id}`, `PUT/DELETE /carts/{id}/items/{sku}` (ETag / If-Match), `POST /checkouts` (Idempotency-Key, `expectedTotal`, 202 + Location) |

## Pricing (domain/pricing.py)

- Unit price = the sale price if there is one, otherwise the list price. Prices include VAT.
- Shipping: STANDARD 4.99 (free from a 50.00 subtotal), EXPRESS 9.99.
- `tax` = the VAT contained in each line and in shipping at 19 %, rounded half-even per line (guide §6.2).
- `total` = subtotal + shipping. The client's `expectedTotal` must match it, or the request gets 422 `price-changed` (the "reread value" countermeasure, architecture §9).

## Decisions and trade-offs

- **Local read model, no synchronous call to catalog-svc** (ADR-0010). Checkout keeps working while catalog-svc is down. The cost is staleness, which is made visible as `pricedAt` and neutralised by `expectedTotal`. Each part of a `catalog_view` row (product, price, stock) has its own version guard.
- **Idempotency through edacommon** (ADR-0012). The response is stored in the business transaction. A concurrent duplicate gets 409 straight away (advisory lock). The same key with another body gets 422. A refused request (for example a price mismatch) does not use up the key.
- **The checkout row, the cart status change and the outbox row commit together.** A 202 therefore always means a `CheckoutSubmitted` will be published (SLO 10).
- **Advisory availability is enforced at add-to-cart**, as `checkout.yaml` allows. The reservation is still the real check. See the top-level README for the SKU-1006 drill consequence.
- **Envelope of `CheckoutSubmitted`:** `aggregateType=Checkout`, `aggregateId=checkoutId`, `partitionKey=correlationId=orderId`, causation null (started by HTTP).
