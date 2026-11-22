# order-svc (Python)

Holds the order aggregate and orchestrates the **order saga**. It renders invoices and serves the Orders API. The same codebase runs the **order-history projector** (`order-svc projector`, group `order-history-projector`). Port 8103, consumer group `order-svc`.

## Owns

`orders` + `order_line` (write model), `saga_instance` + `saga_transition` (shared saga tables), `invoice` + `invoice_counter`, and the schema `order_history` (read model, owned by the projector).

## Topics and APIs

| | |
|---|---|
| Consumes (saga) | `checkout.events.v1`, `inventory.events.v1`, `payment.events.v1`, `fulfilment.events.v1`, `shipping.events.v1` |
| Publishes | `order.events.v1` (OrderPlaced, OrderConfirmed, OrderCancelled, OrderShipped, OrderDelivered, InvoiceIssued, OrderRequiresAttention); commands on `inventory.commands.v1`, `payment.commands.v1`, `fulfilment.commands.v1` |
| Projector consumes | `order.events.v1`, `payment.events.v1`, `fulfilment.events.v1`, `shipping.events.v1`, `returns.events.v1`, `notification.events.v1` |
| HTTP | `GET /orders/{id}` (ETag, 304, `Retry-After`, write-model fallback), `GET /orders/{id}/invoice` (302 to a 5-minute pre-signed URL), `GET /customers/me/orders` (cursor), `GET /ops/sagas/{id}`, `POST /ops/sagas/{id}/retry-step`, `/ops/dlq*` |
| Config | `SAGA_STOCK_TIMEOUT`, `SAGA_PAYMENT_TIMEOUT`, `SAGA_COMMIT_TIMEOUT`, `SAGA_FULFILMENT_ACK_TIMEOUT`, `SAGA_FULFILMENT_MAX_RESENDS`, `SAGA_DISPATCH_TIMEOUT`, `SAGA_CAPTURE_TIMEOUT`, `SAGA_COMPENSATION_TIMEOUT`, `S3_*` |

## Layout

- `domain/saga.py`: the state machine of architecture §5.1/§5.2 as one pure function, `transition(state, data, attempts, trigger, now, timeouts, mint, deadline) -> Decision`. Every branch is commented with its rule.
- `application/handle_saga_trigger.py`: runs one trigger inside `edacommon.saga.SagaEngine`. It maps decisions to messages (`messages.py`), issues the invoice, and updates the write model.
- `adapters/inbound/messaging/handlers.py`: the translation table from contract record to saga trigger.
- `adapters/inbound/jobs/deadlines.py`: the deadline sweeper. `adapters/outbound/documents/`: fpdf2 PDF and the claim-check store. `adapters/projector/`: the read model.

## Decisions and trade-offs

- **DB state machine, not Temporal** (ADR-0008). Saga state, outbox rows, the transition log and the inbox commit in one transaction. The transition table is pure and is tested row by row, plus a Hypothesis property test with participant models (lost, duplicated and reordered replies). The cost: we own timers and retries, through edacommon's sweeper.
- **Early events are stored, not rejected** (§5.3 rule 4). `OrderDispatched` before `OrderPacked`, or `ShipmentDelivered` before `PaymentCaptured`, goes to `data.early` and is applied when the saga reaches the right state, inside the same transition. `OrderPacked` while still waiting for the acknowledgement implies acceptance.
- **Late replies compensate** (rule 3). A `PaymentAuthorized` while cancelling, or after cancellation, sends `VoidPayment`. A `StockReserved` after cancellation (and not after expiry or release) sends `ReleaseReservation`.
- **Compensations resend forever with backoff** (60 s × min(2ⁿ, 16)). After 10 attempts `OrderRequiresAttention` is emitted once, and the saga stays in CANCELLING.
- **Retryable capture failures** back off 1 min, 2 min, ... up to 1 h, with no cap. Past the pivot the only escape is a human (ADR-0015).
- **Versions.** A transition that emits *n* events advances the saga version by *n*, so `aggregateVersion` on `order.events.v1` stays strictly increasing even when `OrderShipped` and `InvoiceIssued` leave together.
- **Invoice: object first, event second** (ADR-0009). The number is gapless (counter row locked in the transaction). The PDF is uploaded under `order/yyyy/mm/{orderId}/{invoiceId}.pdf`, with `invoiceId` minted when the saga enters CAPTURING, so a retry overwrites the same object. Only then is `InvoiceIssued` written. If S3 is down, the error is Transient: the partition retries in place and no event points at a missing object.
- **A reply for an unknown order is `RetryLater`.** `CheckoutSubmitted` travels on another topic, so a reply can race ahead of it. The retry topics give it 10 s, 1 min and 10 min to catch up.
- **Read model with write-model fallback** (ADR-0010). Order events are version-guarded. Events from other contexts only add timeline entries (deduplicated by eventId) and side facts. Rebuilding into `order_history_v2` with a new group gives identical rows (tested). Return status updates come from returns events, which carry the return aggregate's version and are not version-guarded against order events.
