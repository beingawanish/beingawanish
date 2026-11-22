# shipping-svc (port 8107)

Carrier bookings and shipping labels (claim check), tracking normalisation of signed, duplicated and reordered carrier webhooks, return labels for the returns saga. Fake carrier included (admin.yaml `FakeCarrierConfig`).

**Owns:** `shipment`, `tracking_event` (`V2__shipping.sql`) plus the shared tables.
**Consumes:** `fulfilment.events.v1` (OrderPacked -> book outbound; others ignored), `shipping.commands.v1` (IssueReturnLabel), `POST /webhooks/carrier`. **Publishes:** `shipping.events.v1` (ShipmentCreated, ShipmentInTransit, ShipmentDelivered, ShipmentException; key orderId, aggregate Shipment/shipmentId).
**HTTP:** `POST /webhooks/carrier` (webhooks.yaml), `PUT /admin/fakes/carrier`, `POST /admin/fakes/carrier/shipments/{trackingNumber}/advance` (admin.yaml; `GET /admin/fakes/carrier` returns the knobs), `/ops/dlq`, `/health/*`.
**Config:** `CARRIER_WEBHOOK_SECRET` (dev-carrier-secret), `CARRIER_WEBHOOK_URL` (http://localhost:8107/webhooks/carrier), `FAKE_CARRIER_DUPLICATE_RATE` (0.2), `FAKE_CARRIER_OUT_OF_ORDER_RATE` (0.2), `FAKE_CARRIER_EXCEPTION_RATE` (0.02), `FAKE_CARRIER_STEP_DELAY_MS` (30000), `FAKE_CARRIER_BOOKING_FAILURE_RATE` (0.02).

**Patterns:** choreography with fulfilment (ADR-0001); anti-corruption layer (`Carrier` port, carrier vocabulary mapped to `CarrierStatus` ranks); webhook store-then-ack (`WebhookReceiver`: HMAC over `"<ts>.<body>"`, 300 s, inbox on `carrierEventId`, raw row in `tracking_event`, applied afterwards by a job in carrier-timestamp order, webhooks.yaml rules 1-4); claim check for labels (bucket `shipping-labels`, key `shipping/<yyyy>/<mm>/<orderId>/<shipmentId>.pdf`, `expiresAt` = booked + 30 days, OpenPDF); idempotency on `shipmentId` (outbound: minted here, one per fulfilmentId; return: minted by the returns saga).

## Decisions and trade-offs

- **Forward-only tracking (architecture §5.10).** Ranks LABEL_CREATED=0 .. DELIVERED=4; an update at or below the current rank is stored for audit and emits nothing; EXCEPTION is reported for every new carrier event (unknown codes become UNKNOWN). Downstream sees each status at most once and never backwards: exactly one ShipmentDelivered per shipment.
- **Webhooks stored together are applied in `occurredAt` order,** so a burst that arrived reversed still produces IN_TRANSIT before DELIVERED; a DELIVERED that arrives alone first wins, and the late IN_TRANSIT is history only.
- **Booking inside the consumer's transaction, retried by a job.** The fake carrier is idempotent on shipmentId (tracking number derived from it, the same derivation as the Python fake), so a rollback re-books the same parcel. An unavailable carrier is retried after 10 s, 1 min, 10 min, 1 h; after 5 attempts the shipment is BOOKING_FAILED and ShipmentException(BOOKING_FAILED) is published (the order saga's dispatch deadline then raises NEEDS_ATTENTION). A repeated OrderPacked or IssueReturnLabel restarts a failed booking (forward recovery).
- **A repeated OrderPacked or IssueReturnLabel for a booked shipment re-emits ShipmentCreated** with its original aggregateVersion; downstream dispatch and notification are idempotent.
- **Tracking events are external triggers:** their events carry the shipment's correlation id (orderId outbound, returnId for returns) and `causationId = null`.
- **The fake carrier is driven by a tick on the service clock** (500 ms job; `FakeCarrier.tick` in tests); `stepDelayMs <= 0` disables automatic progress and `advance` schedules the next webhook. Its timestamps are RFC 3339 UTC with milliseconds and `Z`.
- **An update for an unknown tracking number is marked IGNORED_UNKNOWN_SHIPMENT,** not retried forever; the raw row stays for audit.
