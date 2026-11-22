# fulfilment-svc (Python)

Runs warehouse orders (pick, pack, dispatch) and returns intake (receipt, inspection) through a WMS port, with the fake WMS of `contracts/openapi/admin.yaml`. It uploads packing manifests by claim check. Port 8106, consumer group `fulfilment-svc`.

## Owns

`fulfilment` (one row per `fulfilmentId`, including the ship-to address), `parcel`, `return_intake`, plus the shared `outbox`, `inbox` and `idempotency_key`.

## Topics and APIs

| | |
|---|---|
| Consumes | `fulfilment.commands.v1`: RequestFulfilment, CancelFulfilment, ExpectReturn. `shipping.events.v1`: ShipmentCreated (OUTBOUND → dispatch), ShipmentDelivered (RETURN → intake); other types are ignored |
| Publishes | `fulfilment.events.v1`: FulfilmentAccepted, OrderPicked, OrderPacked (manifest claim check), OrderDispatched, FulfilmentCancelled, FulfilmentFailed, ReturnReceived, ReturnInspected |
| HTTP | `PUT /admin/fakes/wms`, `/ops/dlq*`, `/health/*` |
| Config | `FAKE_WMS_DROP_REQUEST_RATE`, `FAKE_WMS_ACCEPT_DELAY_MS`, `FAKE_WMS_PICK_DELAY_MS`, `FAKE_WMS_PACK_DELAY_MS`, `FAKE_WMS_FAIL_RATE`, `FAKE_WMS_MANIFEST_LINES`, `FAKE_WMS_INSPECTION_DAMAGED_RATE`, `S3_*`, plus guide §7 |

## Layout

- `domain/model.py`: the fulfilment lifecycle and the decisions for request, cancel, warehouse progress and dispatch, plus return intake, inspection grouping and parcel planning. All pure.
- `application/use_cases.py`: `Fulfilments`, the use cases. `ports.py` defines `Warehouse` (asynchronous: submit, then `poll`/`ack` progress), `ManifestStore`, `FulfilmentRepository` and `EventPublisher`.
- `adapters/outbound/wms/fake/wms.py`: the fake WMS. It is lossy, slow, dedupes on `fulfilmentId`, generates a manifest of about 500 KB, and inspects returns.
- `adapters/inbound/jobs/warehouse.py`: the pump that applies WMS progress, one transaction per WMS event, acknowledged after commit.

## Patterns used

Inbox, idempotent business ids (a resend re-emits the original reply), transactional outbox, claim check (object first, event second), anti-corruption layer and fake behind a port, choreography with shipping-svc (ADR-0001).

## Decisions and trade-offs

- **A resend that the warehouse has not acknowledged is pushed to the WMS again** (architecture §5.8). A resend after acknowledgement re-emits the original `FulfilmentAccepted`. The WMS dedupes on `fulfilmentId`, so the result is one pick order, and the chaos-wms test checks that. When the WMS sees a resubmission it *re-announces* progress it already made, so a progress message lost between the WMS and us is recovered by the saga's next resend. The cost: the WMS adapter needs a dedupe key, which every real WMS supports in some form.
- **The WMS is asynchronous behind `poll`/`ack`.** A WMS event is acknowledged only after its transaction commits. If S3 is down while a manifest uploads, the event stays queued and nothing points at a missing object (the chaos-minio drill). The cost is a pump thread that polls every 500 ms. A real WMS with callbacks would use store-then-ack like the webhooks instead.
- **Manifest key from business ids and the fulfilment's creation month** (`fulfilment/yyyy/mm/{orderId}/{fulfilmentId}.json`, ADR-0009). A retry overwrites the same object even across a month boundary. `expiresAt` = packed time + 90 days, matching the bucket lifecycle rule.
- **Dispatch happens on `ShipmentCreated(OUTBOUND)`** (architecture §5.4). The fake has no separate carrier pickup scan for outbound parcels. A booking for a cancelled or failed fulfilment is ignored, and its label is left unused.
- **Cancel tombstones and the pivot.** A `CancelFulfilment` for an unknown id writes a `CANCELLED` row, so a late `RequestFulfilment` cannot start picking. Cancelling a dispatched order is a `DomainError`, so it goes to the DLQ: past the pivot only a human decides (ADR-0015).
- **Async replies keep their causation.** WMS-driven events carry `causationId` = the last `RequestFulfilment` (stored as `last_command_id`). `ReturnInspected` points at the delivery event that started the inspection.
- **Fake simplification.** WMS state is in memory, like the fake PSP. After a restart the fake has forgotten its pick orders. The saga's resends recreate them, but the progress of a pick order that was in flight starts again.
