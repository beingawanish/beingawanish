"""Warehouse event pump: applies the WMS's progress (accepted, picked, packed, failed, inspected).

One transaction per WMS event. An event is acknowledged to the WMS only after its transaction
committed, so a crash (or an object-store outage while uploading a manifest) leaves it to be applied
on the next tick; the use cases are idempotent by state.
"""

from __future__ import annotations

from collections.abc import Callable

from edacommon.db import Database, UnitOfWork
from edacommon.errors import Transient, classify
from edacommon.ids import Clock
from edacommon.logging import get_logger

from fulfilment_svc.application.ports import InspectionReport, Warehouse
from fulfilment_svc.application.use_cases import Fulfilments

log = get_logger(__name__)


class WarehouseEventPump:
    def __init__(
        self, db: Database, warehouse: Warehouse, fulfilments_for: Callable[[UnitOfWork], Fulfilments], clock: Clock
    ) -> None:
        self._db = db
        self._warehouse = warehouse
        self._fulfilments_for = fulfilments_for
        self._clock = clock

    def run_once(self) -> int:
        applied = 0
        for ev in self._warehouse.poll(self._clock.now()):
            try:
                with self._db.unit_of_work() as uow:
                    uc = self._fulfilments_for(uow)
                    now = self._clock.now()
                    result = uc.on_inspection(ev, now) if isinstance(ev, InspectionReport) else uc.on_warehouse_event(ev, now)
            except Exception as exc:
                level = log.warning if classify(exc) is Transient else log.error
                level("warehouse event failed; retrying on the next tick", wms_event_id=ev.event_id, error=exc)
                continue
            if result is None:
                continue  # the row is not visible yet; keep the event
            self._warehouse.ack(ev.event_id)
            applied += int(result)
        return applied
