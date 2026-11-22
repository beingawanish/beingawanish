# notification-svc (port 8108)

Customer emails as choreographed reactions to order, shipping and returns facts, with invoice and return-label attachments fetched from claim checks. Owns contact details (learnt from OrderPlaced) under its own retention.

**Owns:** `contact`, `notification` (`V2__notification.sql`) plus the shared tables.
**Consumes:** `order.events.v1` (OrderPlaced -> contact; OrderConfirmed, OrderCancelled, OrderShipped, InvoiceIssued, OrderDelivered), `shipping.events.v1` (ShipmentCreated RETURN -> label email; ShipmentException outbound), `returns.events.v1` (ReturnAuthorized, ReturnRejected, ReturnRefunded, ReturnClosed EXPIRED), `payment.events.v1` (subscribed per topics.yaml; no message needs a payment fact, so the runtime ignores them). **Publishes:** `notification.events.v1` (NotificationSent; key orderId, customerId without an order; aggregate Notification/notificationId).
**HTTP:** `/ops/dlq`, `/health/*`.
**Config:** `notification.contact-retention` (400 days), sweep every hour.

**Templates:** `order-confirmed`, `order-cancelled`, `order-shipped`, `invoice` (PDF attached), `order-delivered`, `shipment-problem`, `return-authorized`, `return-label` (PDF attached), `return-rejected`, `return-refunded`, `return-expired`.

**Patterns:** choreography (ADR-0001: producers do not know this service exists); two levels of dedupe: the inbox (same eventId) and a dedupe key `template:businessId` (the same fact re-emitted with a new eventId, e.g. a re-emitted ShipmentCreated); claim check consumer (ADR-0009: download, verify size and SHA-256; missing object -> RetryLater through the retry topics; tampered -> NonRetryable; expired -> send without the attachment); PII kept in one place (ADR-0013).

## Decisions and trade-offs

- **The email is sent inside the consumer's transaction** with the gateway's idempotency key set to the dedupe key. A rollback after the send and a redelivery re-sends with the same key, which the gateway (the fake, and real providers that support it) delivers once. The alternative, a separate sender job over a pending table, adds a state and a table for little gain here.
- **Facts before their contact wait** (RetryLater): OrderPlaced is on the same topic as the other order facts but a retried record can overtake it, and shipping/returns facts are on other topics.
- **Operational facts send nothing:** an outbound BOOKING_FAILED or a return exception is for operations, a return closed as REFUNDED is already announced by ReturnRefunded.
- **Contacts are deleted after 400 days** (longer than the return window after the latest delivery). Logs carry ids and template names only; a test greps captured output for the seeded email address and name.
- **Only EMAIL is implemented.** SMS and PUSH exist in the contract enum; the gateway port is where they would be added.
