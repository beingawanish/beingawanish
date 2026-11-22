# shipping-svc (Python)

Books carriers and labels (label PDF by claim check) and normalises the carrier's duplicated and reordered tracking webhooks. It includes the fake carrier of `contracts/openapi/admin.yaml`. Port 8107, consumer group `shipping-svc`.

## Owns

`shipment` (one per outbound fulfilment and one per return label; it holds the address printed on the label), `tracking_event` (every raw carrier webhook, kept for audit), plus the shared tables.

## Topics and APIs

| | |
|---|---|
| Consumes | `fulfilment.events.v1`: OrderPacked (choreography; the other types are ignored). `shipping.commands.v1`: IssueReturnLabel. Carrier webhooks over HTTP |
| Publishes | `shipping.events.v1`: ShipmentCreated, ShipmentInTransit, ShipmentDelivered, ShipmentException |
| HTTP | `POST /webhooks/carrier` (HMAC, 300 s tolerance), `PUT /admin/fakes/carrier`, `POST /admin/fakes/carrier/shipments/{trackingNumber}/advance`, `/ops/dlq*`, `/health/*` |
| Config | `CARRIER_WEBHOOK_SECRET`, `CARRIER_WEBHOOK_URL`, `FAKE_CARRIER_DUPLICATE_RATE`, `FAKE_CARRIER_OUT_OF_ORDER_RATE`, `FAKE_CARRIER_EXCEPTION_RATE`, `FAKE_CARRIER_STEP_DELAY_MS`, `FAKE_CARRIER_BOOKING_FAILURE_RATE`, `S3_*` |

## Layout

- `domain/model.py`: the booking states, the retry schedule (10 s, 1 min, 10 min, 1 h, then give up) and `normalise(rank, status)`, the forward-only tracking rule of architecture §5.10.
- `application/use_cases.py`: `Shipments` (book outbound, issue return labels, retry bookings, apply tracking updates).
- `adapters/outbound/carrier/acl.py`: the anti-corruption layer for the carrier vocabulary. `carrier/fake/carrier.py`: the fake carrier. `documents/label_pdf.py`: the fpdf2 label.
- `adapters/inbound/jobs/workers.py`: `TrackingProcessor` (applies stored webhooks) and `BookingRetrier`.

## Patterns used

Store-then-ack webhooks with inbox dedupe (`carrier-webhook`), idempotent business ids (`shipmentId`; one shipment per `fulfilmentId`), claim check, anti-corruption layer with a fake behind the port, a forward-recovery retry schedule, and transactional outbox.

## Decisions and trade-offs

- **Normalise by rank, not by arrival** (architecture §5.10). Ranks are LABEL_CREATED 0 to DELIVERED 4. Only forward moves are emitted, and EXCEPTION is emitted whenever it is seen (once per `carrierEventId`, enforced by the inbox). PICKED_UP, IN_TRANSIT and OUT_FOR_DELIVERY all become `ShipmentInTransit`. A unit test runs every arrival order of the four statuses, each twice, and checks that the emitted ranks are strictly increasing with exactly one delivery. The cost: a late scan never reaches the timeline, though it is still in `tracking_event`.
- **The carrier is called inside the consumer transaction.** That is safe because booking is idempotent on `shipmentId`, and the fake derives the tracking number from it. This is the same trade-off payment-svc makes with the PSP.
- **Booking failures retry on a schedule, not on the retry topics.** A failure is expected (`bookingFailureRate`), so it stays out of the DLQ. After 5 attempts the service emits `ShipmentException(BOOKING_FAILED)` and stops. A resent `IssueReturnLabel` for a failed return booking restarts the attempts, which is forward recovery driven by the returns saga's label timeout. For an outbound booking that gave up, the order saga's dispatch deadline sends the order to NEEDS_ATTENTION (ADR-0001 "when to revisit").
- **A webhook for an unknown tracking number is kept for an hour.** The carrier can be faster than our booking commit. After that it is marked `ORPHAN`.
- **Webhook events have no causation.** They start from an external HTTP request (Envelope doc). The correlation is the shipment's: the orderId outbound, the returnId for returns.
- **Label key** `shipping/yyyy/mm/{orderId}/{shipmentId}.pdf`, with `expiresAt` = booking + 30 days (the bucket lifecycle rule).
- **Extension:** the advance endpoint also accepts `exceptionCode` next to `toStatus` (default `DELAYED`). The contract only has `toStatus`.
- **Fake simplification.** Tracking plans are in memory and use wall-clock time.
