# notification-svc (Python)

Sends customer emails for order, shipping, payment and returns events, with invoice and label PDFs attached from claim checks. It owns contact details for messaging. Port 8108, consumer group `notification-svc`.

## Owns

`contact`, `order_contact` (personal data learnt from `OrderPlaced`), `notification` (one row per message sent, unique `dedupe_key`), plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Consumes | `order.events.v1` (OrderPlaced → contact store; OrderConfirmed, OrderCancelled, OrderShipped, InvoiceIssued, OrderDelivered), `payment.events.v1` (RefundSucceeded without a return), `shipping.events.v1` (ShipmentCreated RETURN → label email; ShipmentException OUTBOUND), `returns.events.v1` (ReturnAuthorized, ReturnRejected, ReturnRefunded, ReturnClosed EXPIRED) |
| Publishes | `notification.events.v1`: NotificationSent (key orderId) |
| HTTP | `/ops/dlq*`, `/health/*` |
| Config | guide §7 only (`S3_*` for attachments) |

## Layout

- `domain/templates.py`: `Notice` (template, business id, facts, attachments), the dedupe key, and pure rendering.
- `application/notifications.py`: one use case. It checks the dedupe key, fetches and verifies attachments, sends, then writes the `notification` row and `NotificationSent`.
- `adapters/inbound/messaging/handlers.py`: the translation table from contract record to `Notice`. A new reaction is one row there plus a template.
- `adapters/outbound/mail/fake/mailer.py`: the fake mail gateway (an in-memory outbox that dedupes on the idempotency key).

## Patterns used

Choreography (pure listeners, ADR-0001), inbox plus a business-level dedupe key, claim-check consumer (download, then verify size and SHA-256), transactional outbox, and PII kept out of events and logs (ADR-0013).

## Decisions and trade-offs

- **Two dedupe layers.** The inbox drops redelivered events (same eventId). `notification.dedupe_key` = template + business id (orderId, invoiceId, shipmentId, refundId, returnId) also drops a fact that a producer re-emitted with a new eventId, such as shipping-svc answering a resent `IssueReturnLabel`. The result is one email per triggering business event (tested ×3 redelivery plus a re-emit). The cost: deliberately sending the same template twice for one business id needs a new key scheme.
- **Send inside the transaction, made safe by the gateway's idempotency key** (= the dedupe key). If the commit fails after a send, the redelivery calls the gateway again, and the gateway answers with the original message id. The alternative, a "pending notification" table with a sender worker, adds a second dispatcher for little gain. Revisit this if the mail provider has no idempotency key.
- **Attachments are fetched in the consumer.** A missing object is `RetryLater`, so the message moves through `notification-svc.retry.*`, which is what the chaos-minio drill expects. A hash mismatch is `NonRetryable` and goes to the DLQ. An attachment whose `expiresAt` has passed (an old event replayed) is skipped with a warning (ADR-0009).
- **An event that arrives before its contact** (cross-topic, for example a return email racing `OrderPlaced`) is `RetryLater`.
- **No PII in logs.** Log lines carry `notification_id`, `template` and `order_id`. A test captures the JSON logs and greps them for the seeded email, name and street.
- **`payment.events.v1`** carries only one reaction: refunds that are not part of a return. A return refund is announced by `ReturnRefunded`, so customers do not get two emails.
- **Not built:** `notification-tmp` (rendered attachments) is unused because attachments are sent directly from their source objects. SMS and push channels are not built. Contact erasure waits for `CustomerErased` (ADR-0013).
