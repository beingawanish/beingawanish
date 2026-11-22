"""Composition root of inventory-svc: ``inventory-svc [serve|migrate]``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contracts_py import records as R
from edacommon.db import UnitOfWork
from edacommon.http import Authenticator, Readiness, create_app, dlq_router
from edacommon.idempotency import IdempotencyStore
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, PeriodicTask, SchemaReadiness, ServiceRuntime

from inventory_svc.adapters.inbound.http.routes import admin_router
from inventory_svc.adapters.inbound.jobs.expiry import ExpirySweeper
from inventory_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from inventory_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlInventoryRepository
from inventory_svc.application.use_cases import Inventory
from inventory_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"


def inventory_factory(infra: Infrastructure, settings: Settings) -> Callable[[UnitOfWork], Inventory]:
    def make(uow: UnitOfWork) -> Inventory:
        return Inventory(
            repo=SqlInventoryRepository(uow.session),
            events=OutboxPublisher(uow.session, infra.outbox),
            max_ttl=settings.reservation_ttl,
        )

    return make


def build(settings: Settings, infra: Infrastructure) -> ServiceRuntime:
    inventory_for = inventory_factory(infra, settings)
    registry = build_registry(inventory_for, infra.clock)
    loops = infra.consumer_loops(registry, TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add(
        "schemas",
        SchemaReadiness(
            infra.serde,
            [
                R.StockReserved,
                R.StockReservationRejected,
                R.ReservationCommitted,
                R.ReservationReleased,
                R.ReservationExpired,
                R.ItemsRestocked,
                R.StockLevelChanged,
            ],
        ),
    )
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            admin_router(infra.db, inventory_for, infra.clock, auth),
            dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth),
        ],
    )
    sweeper = ExpirySweeper(infra.db, inventory_for, infra.clock)
    workers: list[Any] = [
        PeriodicTask("reservation-expiry", sweeper.run_once, settings.reservation_sweep_interval),
        infra.housekeeping(),
    ]
    relay = infra.relay()
    if relay:
        workers.append(relay)
    return ServiceRuntime(
        settings=settings, app=app, loops=loops, workers=workers, on_shutdown=[lambda: infra.producer.flush(5), infra.db.dispose]
    )


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "serve"
    settings = Settings()
    migrate(MIGRATIONS, settings.db_url)
    if cmd == "migrate":
        return
    infra = Infrastructure.from_settings(settings)
    build(settings, infra).run()


if __name__ == "__main__":
    main()
