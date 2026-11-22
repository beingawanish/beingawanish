# payment-svc (port 8104)

Authorise, capture, void and refund through the `PaymentGateway` port; the fake PSP implements it. Reconciles unknown outcomes. Receives PSP webhooks.

**Owns:** `payment`, `payment_attempt`, `refund`, `psp_webhook` (`V2__payment.sql`).
**Consumes:** `payment.commands.v1` (AuthorizePayment, CapturePayment, VoidPayment, RefundPayment), `POST /webhooks/psp`. **Publishes:** `payment.events.v1` (key orderId, aggregate Payment/paymentId, or Refund/refundId).
**HTTP:** `POST /webhooks/psp` (webhooks.yaml), `GET/PUT /admin/fakes/psp` (admin.yaml FakePspConfig, PUT merges the given fields), `/ops/dlq`.
**Config:** `PSP_WEBHOOK_SECRET`, `PSP_WEBHOOK_URL`, `FAKE_PSP_DECLINE_RATE`, `FAKE_PSP_TIMEOUT_RATE`, `FAKE_PSP_DUPLICATE_WEBHOOK_RATE`, `FAKE_PSP_WEBHOOK_DELAY_MS`, `FAKE_PSP_SLOW_WEBHOOK_MS`, `FAKE_PSP_API_LATENCY_MS`.

**Fake PSP** (`adapters/out/psp/fake/FakePsp`): authorisations answer "accepted" and the outcome arrives by signed webhook after `webhookDelayMs`. `tok_visa_ok` approves; `tok_decline`, `tok_insufficient_funds`, `tok_fraud` decline; `tok_slow` sends the webhook after `slowWebhookMs`; `tok_dup_webhook` sends every webhook 3 times (same `pspEventId`); `tok_capture_fails` fails capture with `authorization_expired`; `tok_timeout` gives no answer within the client timeout and becomes visible as authorised to status queries after 30 s. Other tokens follow the rates; a random timeout loses the request entirely, so reconciliation ends in `PSP_TIMEOUT` with a void.

**Patterns:** anti-corruption layer (PSP vocabulary only in `PspVocabulary`); idempotency at three levels (inbox, paymentId/refundId, PSP idempotency key); webhook store-then-ack (`WebhookReceiver` + `psp_webhook`, applied by a job); reconciliation of `UNKNOWN` (every 15 s, for 2 min, then void + `PaymentDeclined(PSP_TIMEOUT)`); a late success after that is voided and never reported.

## Decisions and trade-offs

- **PSP calls run inside the consumer's transaction.** A rollback and redelivery repeat the call with the same idempotency key, so this is safe; it holds a DB connection for at most the 5 s client timeout. A separate "PSP request" job would avoid that at the price of another state and table.
- **Void is synchronous, everything else is asynchronous** (webhooks). Voids are the compensation the saga waits for; making them synchronous removes one failure mode.
- **PENDING payments are also reconciled** (after 5 min) so a lost webhook cannot leave a payment pending forever; the fake reports "pending" until its decision time, which keeps the `tok_slow` drill deterministic.
- **A void past capture is NonRetryable** (DLQ): past the pivot only a human decides (ADR-0015).
- **Gap:** admin.yaml has no knob to force refund failures (needed for the Day 8 refund-retry drill); the fake always refunds successfully. Reported as a contract issue.
