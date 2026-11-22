"""Deadline sweeper (ADR-0008): every few seconds, fire ``DEADLINE`` for due sagas.

Each due saga is handled in its own transaction (one transaction per transition) after
``SELECT ... WHERE saga_id = :id AND deadline_at <= now() FOR UPDATE SKIP LOCKED``, so several
replicas sweep in parallel without double work. ``eda.saga.overdue`` is set on every run: sagas with
``deadline_at < now - 60 s``. It should always be 0.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import timedelta

from edacommon.db import Database, UnitOfWork
from edacommon.errors import classify, Transient
from edacommon.ids import Clock
from edacommon.logging import get_logger
from edacommon.metrics import EdaMetrics
from edacommon.saga.repository import SagaRepository, SagaRow

log = get_logger(__name__)
OVERDUE_GRACE = timedelta(seconds=60)


class DeadlineSweeper:
    def __init__(self, *, db: Database, saga_type: str, on_deadline: Callable[[UnitOfWork, SagaRow], None],
                 clock: Clock, metrics: EdaMetrics, interval: timedelta = timedelta(seconds=5),
                 batch: int = 100) -> None:
        self._db = db
        self._type = saga_type
        self._on_deadline = on_deadline
        self._clock = clock
        self._metrics = metrics
        self._interval = interval.total_seconds()
        self._batch = batch
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> int:
        now = self._clock.now()
        with self._db.unit_of_work() as uow:
            due = SagaRepository(uow.session).due_ids(self._type, now, self._batch)
        handled = 0
        for saga_id in due:
            try:
                with self._db.unit_of_work() as uow:
                    row = SagaRepository(uow.session).lock_if_due(saga_id, self._clock.now())
                    if row is None:
                        continue  # another replica has it, or a reply moved the deadline
                    self._on_deadline(uow, row)
                    handled += 1
            except Exception as exc:
                level = log.warning if classify(exc) is Transient else log.error
                level("deadline handling failed; will retry on the next sweep", saga_id=saga_id, error=exc)
        with self._db.unit_of_work() as uow:
            overdue = SagaRepository(uow.session).count_overdue(self._type, self._clock.now() - OVERDUE_GRACE)
        self._metrics.saga_overdue(saga_type=self._type, count=overdue)
        return handled

    def run(self) -> None:
        log.info("deadline sweeper started", saga_type=self._type)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception as exc:
                log.warning("deadline sweep failed", error=exc)
            self._stop.wait(self._interval)
        log.info("deadline sweeper stopped", saga_type=self._type)
