"""The fake warehouse (admin.yaml ``FakeWmsConfig``): an outbound adapter behind the :class:`Warehouse`
port. It is slow and lossy on purpose.

* ``dropRequestRate``: a new pick order is silently "lost" (never accepted). The saga's deadline
  resends ``RequestFulfilment`` and fulfilment-svc pushes it again (architecture §5.8).
* The warehouse dedupes on ``fulfilmentId``: a resubmission never creates a second pick order. It
  re-announces the progress it already made instead, like a WMS answering "already exists, status X",
  so a progress message lost between the WMS and us is recovered by the next resend.
* ``acceptDelayMs``, ``pickDelayMs``, ``packDelayMs``: progress is scheduled on the injected clock and
  delivered through :meth:`poll`; :meth:`ack` removes an event once its transaction committed.
* ``failRate``: the order ends in ``FulfilmentFailed(STOCK_DAMAGED)`` at packing time.
* ``manifestLines``: size of the packing manifest (per-item scans, lot and serial numbers); 2,000 lines
  are about 500 KB, which is what exercises the claim check.
* ``inspectionDamagedRate``: per returned unit, the chance it is inspected as DAMAGED.

State is in memory, like the fake PSP: a restart forgets pick orders, which the saga's resends repair.
"""

from __future__ import annotations

import json
import random
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta

from edacommon.ids import new_id, rfc3339

from fulfilment_svc.application.ports import InspectionReport, WarehouseEvent
from fulfilment_svc.domain.model import (
    FailureReason,
    InspectionOutcome,
    OrderLine,
    ReturnLine,
    WarehouseStep,
    group_outcomes,
    plan_parcels,
)

WAREHOUSE_ID = "wh-berlin-1"


@dataclass(frozen=True)
class FakeWmsConfig:
    dropRequestRate: float = 0.1  # noqa: N815 - API names (admin.yaml)
    acceptDelayMs: int = 2000  # noqa: N815
    pickDelayMs: int = 20000  # noqa: N815
    packDelayMs: int = 20000  # noqa: N815
    failRate: float = 0.02  # noqa: N815
    manifestLines: int = 2000  # noqa: N815
    inspectionDamagedRate: float = 0.2  # noqa: N815

    def merged(self, patch: dict[str, object]) -> FakeWmsConfig:
        allowed = {k: v for k, v in patch.items() if k in asdict(self)}
        return replace(self, **allowed)  # type: ignore[arg-type]


RATES = ("dropRequestRate", "failRate", "inspectionDamagedRate")


@dataclass
class _PickOrder:
    fulfilment_id: str
    order_id: str
    lines: tuple[OrderLine, ...]
    fails: bool
    reached: list[WarehouseEvent] = field(default_factory=list)  # progress already announced
    cancelled: bool = False


class FakeWms:
    """Implements :class:`fulfilment_svc.application.ports.Warehouse`."""

    def __init__(self, config: FakeWmsConfig, *, seed: int | None = None) -> None:
        self.config = config
        self._rng = random.Random(seed)  # noqa: S311 - simulation, not crypto
        self._lock = threading.Lock()
        self._orders: dict[str, _PickOrder] = {}
        self._queue: list[tuple[datetime, WarehouseEvent | InspectionReport]] = []
        self._inspections: set[str] = set()
        self.submissions: Counter[str] = Counter()
        self.dropped: Counter[str] = Counter()

    # ------------------------------------------------------------------------------ port: orders
    def submit_pick_order(self, *, fulfilment_id: str, order_id: str, lines: tuple[OrderLine, ...], now: datetime) -> None:
        with self._lock:
            self.submissions[fulfilment_id] += 1
            existing = self._orders.get(fulfilment_id)
            if existing is not None:
                # Dedupe on fulfilmentId; re-announce what already happened (fresh event ids).
                for ev in existing.reached:
                    self._queue.append((now, replace(ev, event_id=new_id())))
                return
            if self._rng.random() < self.config.dropRequestRate:
                self.dropped[fulfilment_id] += 1
                return  # silently lost
            po = _PickOrder(fulfilment_id, order_id, lines, fails=self._rng.random() < self.config.failRate)
            self._orders[fulfilment_id] = po
            self._schedule(po, now)

    def _schedule(self, po: _PickOrder, now: datetime) -> None:
        c = self.config
        accept_at = now + timedelta(milliseconds=c.acceptDelayMs)
        pick_at = accept_at + timedelta(milliseconds=c.pickDelayMs)
        pack_at = pick_at + timedelta(milliseconds=c.packDelayMs)
        fid = po.fulfilment_id
        self._queue.append(
            (
                accept_at,
                WarehouseEvent(
                    new_id(),
                    fid,
                    WarehouseStep.ACCEPTED,
                    accept_at,
                    warehouse_id=WAREHOUSE_ID,
                    estimated_dispatch_at=pack_at + timedelta(hours=2),
                ),
            )
        )
        self._queue.append((pick_at, WarehouseEvent(new_id(), fid, WarehouseStep.PICKED, pick_at)))
        if po.fails:
            self._queue.append(
                (
                    pack_at,
                    WarehouseEvent(
                        new_id(),
                        fid,
                        WarehouseStep.FAILED,
                        pack_at,
                        failure_reason=FailureReason.STOCK_DAMAGED.value,
                        failure_detail="item damaged at the packing station",
                    ),
                )
            )
        else:
            parcels = plan_parcels(po.lines, lambda i: f"{fid}-p{i + 1}")
            manifest = self._manifest(po, pack_at)
            self._queue.append(
                (pack_at, WarehouseEvent(new_id(), fid, WarehouseStep.PACKED, pack_at, parcels=parcels, manifest=manifest))
            )

    def cancel_pick_order(self, fulfilment_id: str) -> None:
        with self._lock:
            po = self._orders.get(fulfilment_id)
            if po is not None:
                po.cancelled = True
            self._queue = [
                (t, e) for t, e in self._queue if not (isinstance(e, WarehouseEvent) and e.fulfilment_id == fulfilment_id)
            ]

    # ----------------------------------------------------------------------------- port: returns
    def inspect_return(self, *, return_id: str, lines: tuple[ReturnLine, ...], now: datetime) -> None:
        with self._lock:
            if return_id in self._inspections:
                return
            self._inspections.add(return_id)
            results = []
            for line in lines:
                outcomes = [
                    InspectionOutcome.DAMAGED
                    if self._rng.random() < self.config.inspectionDamagedRate
                    else InspectionOutcome.RESTOCKABLE
                    for _ in range(line.quantity)
                ]
                results.extend(group_outcomes(line, outcomes))
            at = now + timedelta(milliseconds=self.config.packDelayMs)
            self._queue.append((at, InspectionReport(new_id(), return_id, at, tuple(results))))

    # ---------------------------------------------------------------------------- port: progress
    def poll(self, now: datetime) -> list[WarehouseEvent | InspectionReport]:
        with self._lock:
            due = sorted((x for x in self._queue if x[0] <= now), key=lambda x: x[0])
            return [e for _, e in due]

    def ack(self, event_id: str) -> None:
        with self._lock:
            for i, (_, e) in enumerate(self._queue):
                if e.event_id == event_id:
                    del self._queue[i]
                    if isinstance(e, WarehouseEvent):
                        po = self._orders.get(e.fulfilment_id)
                        if po is not None and all(r.step is not e.step for r in po.reached):
                            po.reached.append(e)
                    return

    # ------------------------------------------------------------------------------- internals
    def _manifest(self, po: _PickOrder, at: datetime) -> bytes:
        """Per-item scans with lot and serial numbers; deterministic for a fulfilment."""
        rng = random.Random(po.fulfilment_id)  # noqa: S311
        units = [(x.line_id, x.sku) for x in po.lines for _ in range(x.quantity)] or [("-", "-")]
        n = max(self.config.manifestLines, 1)
        scans = []
        for i in range(n):
            line_id, sku = units[i % len(units)]
            scans.append(
                {
                    "seq": i + 1,
                    "lineId": line_id,
                    "sku": sku,
                    "lot": f"LOT-{rng.randrange(10**6):06d}",
                    "serial": f"SN-{rng.randrange(16**12):012x}",
                    "station": f"PACK-{rng.randrange(1, 13):02d}",
                    "operator": f"op-{rng.randrange(1, 60):02d}",
                    "scannedAt": rfc3339(at - timedelta(seconds=n - i)),
                    "checks": {"weightOk": True, "labelOk": True, "sealIntact": True},
                }
            )
        doc = {
            "fulfilmentId": po.fulfilment_id,
            "orderId": po.order_id,
            "warehouseId": WAREHOUSE_ID,
            "generatedAt": rfc3339(at),
            "scans": scans,
        }
        return json.dumps(doc, separators=(",", ":")).encode()

    # ------------------------------------------------------------------------------- test aids
    def pick_orders(self, fulfilment_id: str) -> int:
        """Distinct pick orders the warehouse holds for a fulfilment (always 0 or 1)."""
        return 1 if fulfilment_id in self._orders else 0
