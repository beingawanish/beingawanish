# payment-svc (Python)

Authorises, captures, voids and refunds through a PSP port. It includes the fake PSP of `contracts/openapi/admin.yaml` and reconciles outcomes it does not know. Port 8104, consumer group `payment-svc`.

## Owns

`payment`, `payment_attempt` (audit of every PSP call), `refund`, `psp_webhook` (raw notifications, store-then-ack), plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Consumes | `payment.commands.v1`: AuthorizePayment, CapturePayment, VoidPayment, RefundPayment |
| Publishes | `payment.events.v1`: PaymentAuthorized, PaymentDeclined, PaymentCaptured, PaymentCaptureFailed, PaymentVoided, RefundSucceeded, RefundFailed |
| HTTP | `POST /webhooks/psp` (HMAC, 300 s tolerance), `GET/PUT /admin/fakes/psp`, `/ops/dlq*`, `/health/*` |
| Config | `PSP_WEBHOOK_SECRET`, `PSP_WEBHOOK_URL`, `FAKE_PSP_DECLINE_RATE`, `FAKE_PSP_TIMEOUT_RATE`, `FAKE_PSP_DUPLICATE_WEBHOOK_RATE`, `FAKE_PSP_WEBHOOK_DELAY_MS`, `FAKE_PSP_SLOW_WEBHOOK_MS`, `FAKE_PSP_API_LATENCY_MS` |

## Layout

- `domain/payment.py`: the payment state machine (`PENDING → AUTHORIZED → CAPTURE_PENDING → CAPTURED`, plus `UNKNOWN`, `DECLINED`, `VOID_PENDING`, `VOIDED`, `CAPTURE_FAILED`), `apply_outcome` (idempotent folding of PSP outcomes), and the reconciliation rules.
- `application/payments.py`: the use cases; `ports.py` holds `PspGateway`, `PaymentRepository` and `EventPublisher`.
- `adapters/outbound/psp/acl.py`: the anti-corruption layer. It is the only code that knows `authorization.failed` or `insufficient_funds`.
- `adapters/outbound/psp/fake/psp.py`: the fake PSP. It is idempotent per merchant reference, honours the magic tokens, and sends signed webhooks asynchronously.
- `adapters/inbound/jobs/workers.py`: `WebhookProcessor` (applies stored webhooks) and `Reconciler` (runs every 15 s; void + `PSP_TIMEOUT` after 2 min).

## Decisions and trade-offs

- **PSP calls inside the consumer transaction.** The payment row is written, the PSP is called with `paymentId` (or `refundId`) as the idempotency key, and the result is applied, all before commit. If the transaction rolls back and the command comes back, the PSP returns the same answer, so nobody is charged twice (ADR-0006 layer 3). This buys a simpler design: no "intent" table and no second dispatcher. The cost: a DB transaction held open for up to the PSP timeout, so `DB_POOL_SIZE` must cover the consumer threads plus HTTP. Revisit this if PSP latency grows, by moving the calls to a worker driven from a `payment_attempt` queue.
- **A timeout is UNKNOWN, not a failure** (architecture §5.6). Reconciliation runs every 15 s for 2 minutes. After that the payment is voided ("safe even if nothing exists") and then declined with `PSP_TIMEOUT`. It is never both. A late `authorization.succeeded` after `PSP_TIMEOUT` is voided, and the saga never hears of it.
- **Store-then-ack webhooks.** The endpoint only verifies the signature, inserts into the inbox (`psp-webhook`), stores the payload and answers 200. Domain processing runs from the stored row, so duplicates (×3 with `tok_dup_webhook`) answer 200 and change nothing.
- **Resends re-drive the PSP.** A resent Authorize/Capture whose answer is still pending calls the PSP again with the same key, and the PSP answers synchronously with the current status. A lost webhook therefore cannot strand a payment.
- **Async replies keep their causation.** Replies produced from a webhook or the reconciler carry `causationId` = the command that asked for them (stored as `last_command_id`), so a trace and the ops view read as one chain.
- **Void after capture goes to the DLQ** (NonRetryable). Past the pivot only a human decides (ADR-0015).
- **Fake simplification.** `tok_timeout` raises the timeout immediately instead of sleeping the 5 s client timeout.
