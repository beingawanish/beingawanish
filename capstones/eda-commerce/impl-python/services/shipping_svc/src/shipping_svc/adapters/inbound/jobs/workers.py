"""Background jobs: apply stored carrier webhooks (store-then-ack), and retry pending bookings."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta

from edacommon.db import Database, UnitOfWork
from edacommon.ids import Clock
from edacommon.logging import get_logger

from shipping_svc.adapters.outbound.carrier.acl import to_update
from shipping_svc.adapters.outbound.persistence.repositories import TrackingEventStore
from shipping_svc.application.use_cases import Shipments

log = get_logger(__name__)
# A webhook can arrive before the booking transaction that created the tracking number commits.
ORPHAN_AFTER = timedelta(hours=1)


class TrackingProcessor:
    """Applies ``tracking_event`` rows written by the webhook endpoint. ``wake()`` after each stored
    webhook keeps latency low; the poll interval is the safety net."""

    def __init__(
        self, db: Database, shipments_for: Callable[[UnitOfWork], Shipments], clock: Clock, interval_s: float = 1.0
    ) -> None:
        self._db = db
        self._shipments_for = shipments_for
        self._clock = clock
        self._interval = interval_s
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.name = "carrier-tracking"

    def wake(self) -> None:
        self._wake.set()

    def run_once(self, limit: int = 100) -> int:
        done = 0
        with self._db.unit_of_work() as uow:
            store = TrackingEventStore(uow.session)
            uc = self._shipments_for(uow)
            for row in store.claim(limit):
                now = self._clock.now()
                outcome, shipment_id = uc.on_tracking(to_update(row.payload, row.received_at), now)
                if outcome == "UNKNOWN_SHIPMENT" and now - row.received_at < ORPHAN_AFTER:
                    continue  # booking not visible yet; try again next tick
                store.mark(row.carrier_event_id, "ORPHAN" if outcome == "UNKNOWN_SHIPMENT" else outcome, shipment_id, now)
                done += 1
        return done

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                n = self.run_once()
            except Exception as exc:
                log.warning("tracking processing failed; retrying", error=exc)
                n = 0
                self._stop.wait(1.0)
            if n == 0:
                self._wake.wait(self._interval)
                self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


class BookingRetrier:
    def __init__(self, db: Database, shipments_for: Callable[[UnitOfWork], Shipments], clock: Clock) -> None:
        self._db = db
        self._shipments_for = shipments_for
        self._clock = clock

    def run_once(self) -> int:
        with self._db.unit_of_work() as uow:
            return self._shipments_for(uow).retry_due_bookings(self._clock.now())
