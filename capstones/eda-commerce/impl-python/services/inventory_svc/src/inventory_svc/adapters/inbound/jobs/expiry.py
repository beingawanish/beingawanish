"""Reservation TTL sweeper (ADR-0016): every RESERVATION_SWEEP_INTERVAL, expire overdue holds.

``FOR UPDATE SKIP LOCKED`` in the repository lets several replicas sweep without double work.
"""

from __future__ import annotations

from collections.abc import Callable

from edacommon.db import Database, UnitOfWork
from edacommon.ids import Clock
from inventory_svc.application.use_cases import Inventory


class ExpirySweeper:
    def __init__(self, db: Database, inventory_for: Callable[[UnitOfWork], Inventory], clock: Clock) -> None:
        self._db = db
        self._inventory_for = inventory_for
        self._clock = clock

    def run_once(self) -> int:
        total = 0
        while True:
            with self._db.unit_of_work() as uow:
                n = self._inventory_for(uow).expire_due(self._clock.now())
            total += n
            if n < 100:
                return total
