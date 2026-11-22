# returns-svc (Python)

Return eligibility, RMA numbers and the **returns saga**, a forward-recovery orchestrator (architecture §6). Port 8109, consumer group `returns-svc`.

## Owns

`eligibility_view` (its own projection of order events, including the pickup address), `return_request` + `return_line` (the API read side, updated in the same transaction as the saga row), `rma_counter` (gapless per year), `saga_instance` + `saga_transition`, plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Consumes | `order.events.v1` (OrderPlaced, OrderConfirmed, OrderDelivered, OrderCancelled → eligibility view), `fulfilment.events.v1` (FulfilmentAccepted → warehouse; ReturnReceived, ReturnInspected), `shipping.events.v1` (ShipmentCreated RETURN, ShipmentException RETURN), `inventory.events.v1` (ItemsRestocked), `payment.events.v1` (RefundSucceeded, RefundFailed) |
| Publishes | `returns.events.v1`: ReturnRequested, ReturnAuthorized, ReturnRejected, ReturnRefunded, ReturnClosed. Commands: IssueReturnLabel, ExpectReturn, RestockItems, RefundPayment |
| HTTP | `POST /returns` (Idempotency-Key), `GET /returns/{id}`, `GET /returns/{id}/label` (302, 5-minute pre-signed URL), `GET /orders/{orderId}/returns`, `POST /ops/returns/{id}/decision`, `GET /ops/sagas/{id}`, `POST /ops/sagas/{id}/retry-step`, `/ops/dlq*` |
| Config | `RETURN_WINDOW_DAYS` (30), `RETURN_AUTO_APPROVE_LIMIT_MINOR` (50000), `RETURN_PARCEL_DUE_DAYS` (14), `S3_*` |

## Layout

- `domain/policy.py`: eligibility (not delivered, window closed, over-quantity, unknown line) and the refund rule (RESTOCKABLE full; DAMAGED full only for merchant fault; MISSING zero; shipping fee for merchant fault on the first return only). Pure.
- `domain/saga.py`: the state machine of architecture §6.1 as one pure function, with the state table in its docstring. A unit test covers every row; a Hypothesis test runs random interleavings of replies, duplicates and deadlines.
- `application/returns.py`: `ReturnsSaga`. It runs triggers through `edacommon.saga.SagaEngine` and follows pass-through states with an internal `CONTINUE`. It keeps `return_request` in step with the saga row and serves the HTTP use cases.
- `adapters/inbound/messaging/handlers.py`: the translation from contract record to trigger. `jobs/deadlines.py`: the edacommon sweeper.

## Patterns used

Orchestrated saga on a DB state machine (ADR-0008), forward recovery (retry schedule plus a human decision instead of compensation), CQRS eligibility projection (ADR-0010), HTTP idempotency keys (ADR-0012), claim-check pre-signed URLs (ADR-0009), and outbox and inbox.

## Decisions and trade-offs

- **Forward recovery, not compensation** (architecture §6.2). After inspection every step is retried until it succeeds, or a human decides through `POST /ops/returns/{id}/decision`. The same `refundId` is used on every attempt. The refund retry schedule (1 min, 10 min, 1 h, then REFUND_REVIEW) is driven by the saga deadline, so the sweeper resends; nothing sleeps. Missing replies (lost refund or restock replies, a label that never came) are also resent on deadlines with backoff.
- **Pass-through states run in one transaction.** REQUESTED → AUTHORIZED → AWAITING_PARCEL happen in the `POST /returns` transaction. The response therefore shows the real current status (`AWAITING_PARCEL` or `MANUAL_REVIEW`), and `saga_transition` has one row per diagram edge (trigger type `AUTO`). The sequence in architecture §6.3 shows `202 {status REQUESTED}`; this build answers with the status after the automatic steps.
- **Eligibility against our own projection, under a row lock.** `POST /returns` locks the order's `eligibility_view` row, so two concurrent returns cannot both take the last unit. Returns that expired, or were rejected before the parcel arrived, give their quantity back; returns rejected after inspection do not, because the items came back.
- **Window = `deliveredAt` + `RETURN_WINDOW_DAYS`.** returns-svc owns this policy. `OrderDelivered.returnWindowEndsAt` from order-svc is not used (see the top-level contract observations).
- **Shipping fee = order total − line totals** (prices are VAT-inclusive). `OrderPlaced` does not carry the fee. The first merchant-fault return claims it in `eligibility_view.shipping_fee_return_id`.
- **Outcomes.** CLOSED keeps the outcome in saga data: REFUNDED when every returned unit was refunded in full, otherwise PARTIALLY_REFUNDED. `CLOSE_WITHOUT_REFUND` closes with `ReturnClosed(MANUAL_REVIEW)` and API status `REJECTED`, because returns.yaml has no CLOSED status. `eda.saga.outcomes{outcome=MANUAL_REVIEW}` is counted on entering MANUAL_REVIEW or REFUND_REVIEW. A late `RefundSucceeded` while in REFUND_REVIEW closes the return as refunded.
- **RMA numbers are gapless** (`RMA-yyyy-nnnnnn`). A counter row per year is locked in the transaction that authorises the return.
- **Known gaps.** AWAITING_INSPECTION has no deadline, because the diagram defines none, and there is no command to resend, so a lost inspection shows up only in `GET /ops/sagas/{id}`. `ExpectReturn` has no reply in the contracts, so it is resent together with every label resend.
