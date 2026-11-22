# fulfilment-svc (port 8106)

Warehouse orders (pick, pack, dispatch) behind a WMS port, packing manifests by claim check, and returns intake with inspection. The fake WMS is slow and lossy on purpose (admin.yaml `FakeWmsConfig`).

**Owns:** `fulfilment`, `parcel`, `return_intake` (`V2__fulfilment.sql`) plus the shared tables.
**Consumes:** `fulfilment.commands.v1` (RequestFulfilment, CancelFulfilment, ExpectReturn), `shipping.events.v1` (ShipmentCreated OUTBOUND -> dispatch; ShipmentDelivered RETURN -> return received; everything else ignored). **Publishes:** `fulfilment.events.v1` (FulfilmentAccepted, OrderPicked, OrderPacked, OrderDispatched, FulfilmentCancelled, FulfilmentFailed with aggregate Fulfilment/fulfilmentId; ReturnReceived, ReturnInspected with aggregate ReturnIntake/returnId; all keyed by orderId).
**HTTP:** `PUT /admin/fakes/wms` (admin.yaml; merges the given fields; `GET` returns the current knobs), `/ops/dlq`, `/health/*`.
**Config:** `FAKE_WMS_DROP_REQUEST_RATE` (0.1), `FAKE_WMS_ACCEPT_DELAY_MS` (2000), `FAKE_WMS_PICK_DELAY_MS` (20000), `FAKE_WMS_PACK_DELAY_MS` (20000), `FAKE_WMS_FAIL_RATE` (0.02), `FAKE_WMS_MANIFEST_LINES` (2000), `FAKE_WMS_INSPECTION_DAMAGED_RATE` (0.2).

**Patterns:** participant of the order saga, idempotent on `fulfilmentId`: an unknown id creates the pick order, a known id the warehouse never acknowledged is pushed again (architecture §5.8), an acknowledged id re-answers the original FulfilmentAccepted (with its original aggregateVersion) and never creates a second pick order. Choreography with shipping (ADR-0001): OrderPacked -> shipping books -> ShipmentCreated -> OrderDispatched. Claim check for the manifest (ADR-0009): bucket `packing-manifests`, key `fulfilment/<yyyy>/<mm>/<orderId>/<fulfilmentId>.json`, `expiresAt` = packed + 90 days; uploaded before the transaction that writes OrderPacked. Anti-corruption layer: `Warehouse` (out) and `WarehouseFeedback` (in) ports; the domain never sees WMS formats.

## Decisions and trade-offs

- **The fake WMS is driven by a tick on the service clock** (`PeriodicJob` every 500 ms, `FakeWms.tick` in tests), not by its own timers. Tests move a `MutableClock` and get deterministic accept/pick/pack/inspect steps; the price is a small polling delay in real runs.
- **Warehouse calls happen inside the command's transaction.** The WMS is idempotent on fulfilmentId, so a rollback and redelivery cannot create a second pick order; a callback that finds no row yet (the submit has not committed) is repeated by the fake on its next tick.
- **A cancel before the request leaves a CANCELLED tombstone,** so a RequestFulfilment arriving late through a retry topic answers FulfilmentCancelled instead of starting a pick. A cancel after dispatch is NonRetryable (DLQ): past the pivot only a human decides (ADR-0015).
- **Warehouse callbacks have no causing message,** so their events carry `causationId = null` and the orderId (or returnId for inspections) as correlation id.
- **Unreported units are MISSING.** The warehouse reports one outcome per unit; results are grouped per (line, outcome); anything the warehouse did not mention is MISSING, which the returns saga refunds as zero.
- **A ShipmentCreated before OrderPacked is RetryLater** (it can only be a reordered retry); for a cancelled or failed fulfilment it is ignored with a warning (the label is unused).
- **Persistence with JdbcTemplate and jsonb columns** for lines, address, manifest and inspection results: they are always read with their row, and the SQL stays visible. ship_to is personal data; `ShipTo.toString()` is redacted.
- **The fake keeps its state in memory.** A restarted fake loses in-flight pick orders, exactly the failure the saga's deadline resends are for.
