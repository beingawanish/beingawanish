# order-svc (port 8103) and order-history-projector

The order aggregate, the **order saga** orchestrator (architecture §5), invoices, and the Orders API. The same jar run with the argument `projector` is the order-history projector (profile `projector`, group `order-history-projector`).

**Owns:** `orders`, `order_line`, `invoice`, `invoice_counter` (`V2__orders.sql`), the shared `saga_instance`/`saga_transition`, and schema `order_history` (`V3__order_history.sql`, written only by the projector).
**Consumes (saga):** `checkout.events.v1`, `inventory.events.v1`, `payment.events.v1`, `fulfilment.events.v1`, `shipping.events.v1`. **Publishes:** `order.events.v1`, `inventory.commands.v1`, `payment.commands.v1`, `fulfilment.commands.v1` (all keyed by orderId).
**Consumes (projector):** `order.events.v1`, `payment.events.v1`, `fulfilment.events.v1`, `shipping.events.v1`, `returns.events.v1`, `notification.events.v1`.
**HTTP:** `GET /orders/{id}` (ETag, 304, Retry-After while not terminal, read model with write-model fallback), `GET /orders/{id}/invoice` (302 to a 5-minute pre-signed URL), `GET /customers/me/orders` (keyset cursor), `GET /ops/sagas/{id}`, `POST /ops/sagas/{id}/retry-step`, `/ops/dlq`.
**Config:** `SAGA_STOCK_TIMEOUT`, `SAGA_PAYMENT_TIMEOUT`, `SAGA_COMMIT_TIMEOUT`, `SAGA_FULFILMENT_ACK_TIMEOUT`, `SAGA_FULFILMENT_MAX_RESENDS`, `SAGA_DISPATCH_TIMEOUT`, `SAGA_CAPTURE_TIMEOUT`, `SAGA_COMPENSATION_TIMEOUT`.

**Patterns:** DB-backed saga (ADR-0008): `domain/OrderSaga` is a pure function `(state, data, trigger, now) -> decision`; `OrderSagaService` runs it through edacommon's `SagaEngine` in one transaction with the inbox, the outbox, the order status and the invoice. Business ids (reservationId, paymentId, fulfilmentId, invoiceId) are minted when a step starts and reused on every resend. Replies are matched by id and state; early events (delivered before captured, packed before accepted) are kept in `data.pending` and applied when the saga reaches the state that expects them. The pivot is dispatch (ADR-0015): after it nothing is compensated, failures go to `NEEDS_ATTENTION`. CQRS read model (ADR-0010) with version guards; claim check for invoices (ADR-0009).

## Decisions and trade-offs

- **CANCELLING waits for every compensation** (release, void, cancel-fulfilment) and resends them with exponential backoff (60 s doubling, capped at 16x), forever; alerting relies on `eda_saga_step_timeouts_total`.
- **Late authorisation after cancel is voided,** even in CANCELLED (rule 3).
- **COMMITTING_STOCK and CAPTURING resend without a limit,** as the step table says; inventory and payment always answer eventually. A captured payment without shipping details waits for ShipmentCreated, then raises NEEDS_ATTENTION at the capture deadline.
- **The dispatch deadline is the earlier of 24 h and two days before the authorisation expires** (ADR-0015).
- **Order events carry their own strictly increasing version** (`data.eventVersion`): a transition emitting n events advances it by n; commands carry the saga row version.
- **Invoices:** number allocated from a per-year counter row locked in the same transaction (gapless), PDF rendered with OpenPDF and stored under `order/<yyyy>/<mm>/<orderId>/<invoiceId>.pdf` before the event is written (object first). The invoiceId is minted at dispatch, so a retried transaction overwrites the same object.
- **Fallback reads report version 0,** so a client never sees the version go backwards when the projection catches up.
- **The projector requires OrderPlaced first** (RetryLater otherwise) and drops stale versions entirely, timeline included; non-order events only add timeline rows keyed by eventId.
