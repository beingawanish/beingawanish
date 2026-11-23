"""Composition root of checkout-svc: ``checkout-svc [serve|migrate]``."""

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
from edacommon.runtime import Infrastructure, SchemaReadiness, ServiceRuntime

from checkout_svc.adapters.inbound.http.routes import checkout_router
from checkout_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from checkout_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlCartRepository, SqlCatalogView
from checkout_svc.application.checkout import Checkout
from checkout_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"


def checkout_factory(infra: Infrastructure) -> Callable[[UnitOfWork], Checkout]:
    return lambda uow: Checkout(
        SqlCartRepository(uow.session), SqlCatalogView(uow.session), OutboxPublisher(uow.session, infra.outbox)
    )


def build(settings: Settings, infra: Infrastructure) -> ServiceRuntime:
    checkout_for = checkout_factory(infra)
    loops = infra.consumer_loops(build_registry(checkout_for), TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("schemas", SchemaReadiness(infra.serde, [R.CheckoutSubmitted]))
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            checkout_router(infra.db, checkout_for, infra.clock, auth, IdempotencyStore(infra.clock)),
            dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth),
        ],
    )
    workers: list[Any] = [infra.housekeeping()]
    relay = infra.relay()
    if relay:
        workers.append(relay)
    return ServiceRuntime(
        settings=settings, app=app, loops=loops, workers=workers, on_shutdown=[lambda: infra.producer.flush(5), infra.db.dispose]
    )


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    settings = Settings()
    migrate(MIGRATIONS, settings.db_url)
    if (args[0] if args else "serve") == "migrate":
        return
    build(settings, Infrastructure.from_settings(settings)).run()


if __name__ == "__main__":
    main()
