"""Deadline sweeper for the order saga: edacommon's DeadlineSweeper with this saga's DEADLINE handler."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from edacommon.db import Database, UnitOfWork
from edacommon.ids import Clock
from edacommon.metrics import EdaMetrics
from edacommon.saga import DeadlineSweeper, SagaRow

from order_svc.application.handle_saga_trigger import OrderSaga
from order_svc.domain.saga import SAGA_TYPE


def order_deadline_sweeper(
    db: Database,
    saga_for: Callable[[UnitOfWork], OrderSaga],
    clock: Clock,
    metrics: EdaMetrics,
    interval: timedelta = timedelta(seconds=5),
) -> DeadlineSweeper:
    def on_deadline(uow: UnitOfWork, row: SagaRow) -> None:
        saga_for(uow).on_deadline(uow, row)

    return DeadlineSweeper(db=db, saga_type=SAGA_TYPE, on_deadline=on_deadline, clock=clock, metrics=metrics, interval=interval)
