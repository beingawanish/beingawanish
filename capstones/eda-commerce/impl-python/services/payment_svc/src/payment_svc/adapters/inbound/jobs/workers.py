"""Background jobs: apply stored PSP webhooks, and reconcile payments whose outcome is unknown."""

from __future__ import annotations

import threading
from collections.abc import Callable

from edacommon.db import Database, UnitOfWork
from edacommon.ids import Clock
from edacommon.logging import get_logger

from payment_svc.adapters.outbound.persistence.repositories import WebhookStore
from payment_svc.adapters.outbound.psp.acl import outcome_from_notification
from payment_svc.application.payments import Payments

log = get_logger(__name__)


class WebhookProcessor:
    """Applies rows of ``psp_webhook`` that the endpoint stored (store-then-ack). ``wake()`` is
    called after each stored webhook so latency stays low; the poll interval is the safety net."""

    def __init__(
        self, db: Database, payments_for: Callable[[UnitOfWork], Payments], clock: Clock, interval_s: float = 1.0
    ) -> None:
        self._db = db
        self._payments_for = payments_for
        self._clock = clock
        self._interval = interval_s
        self._wake = threading.Event()
        self._stop = threading.Event()

    def wake(self) -> None:
        self._wake.set()

    def run_once(self, limit: int = 50) -> int:
        with self._db.unit_of_work() as uow:
            store = WebhookStore(uow.session)
            rows = store.claim(limit)
            payments = self._payments_for(uow)
            for row in rows:
                now = self._clock.now()
                try:
                    ref, outcome = outcome_from_notification(row.payload)
                except ValueError as exc:
                    log.error("unprocessable PSP webhook", psp_event_id=row.psp_event_id, error=exc)
                    store.mark_processed(row.psp_event_id, now)
                    continue
                payments.on_psp_outcome(merchant_reference=ref, outcome=outcome, now=now)
                store.mark_processed(row.psp_event_id, now)
        return len(rows)

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                n = self.run_once()
            except Exception as exc:
                log.warning("webhook processing failed; retrying", error=exc)
                n = 0
                self._stop.wait(1.0)
            if n == 0:
                self._wake.wait(self._interval)
                self._wake.clear()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()


class Reconciler:
    def __init__(self, db: Database, payments_for: Callable[[UnitOfWork], Payments], clock: Clock) -> None:
        self._db = db
        self._payments_for = payments_for
        self._clock = clock

    def run_once(self) -> int:
        with self._db.unit_of_work() as uow:
            return self._payments_for(uow).reconcile_due(self._clock.now())
