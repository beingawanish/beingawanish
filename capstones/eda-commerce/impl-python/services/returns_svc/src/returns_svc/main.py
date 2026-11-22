"""Composition root of returns-svc: ``returns-svc [serve|migrate]``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.db import UnitOfWork
from edacommon.http import Authenticator, Readiness, create_app, dlq_router
from edacommon.idempotency import IdempotencyStore
from edacommon.ids import new_id
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, SchemaReadiness, ServiceRuntime
from edacommon.saga import SagaEngine
from edacommon.saga.ops import saga_ops_router

from returns_svc.adapters.inbound.http.routes import ops_caller, returns_router
from returns_svc.adapters.inbound.jobs.deadlines import returns_deadline_sweeper
from returns_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from returns_svc.adapters.outbound.persistence.repositories import SqlReturnsRepository
from returns_svc.adapters.outbound.storage.labels import ClaimCheckLabelLinks
from returns_svc.application.ports import LabelLinks
from returns_svc.application.returns import ReturnsSaga
from returns_svc.config import Settings
from returns_svc.domain.saga import SAGA_TYPE

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"
PRODUCED = [
    R.ReturnRequested,
    R.ReturnAuthorized,
    R.ReturnRejected,
    R.ReturnRefunded,
    R.ReturnClosed,
    R.IssueReturnLabel,
    R.ExpectReturn,
    R.RestockItems,
    R.RefundPayment,
]


def saga_factory(settings: Settings, infra: Infrastructure) -> Callable[[UnitOfWork], ReturnsSaga]:
    engine = SagaEngine(saga_type=SAGA_TYPE, outbox=infra.outbox, metrics=infra.metrics, clock=infra.clock)
    saga = ReturnsSaga(
        engine=engine,
        repo_for=lambda uow: SqlReturnsRepository(uow.session),
        policy=settings.policy(),
        window=settings.window,
        new_id=new_id,
        clock=infra.clock,
    )
    return lambda uow: saga


def links_from(settings: Settings, infra: Infrastructure) -> LabelLinks:
    return ClaimCheckLabelLinks(
        ClaimCheckStore.from_settings(
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            metrics=infra.metrics,
        )
    )


def build(settings: Settings, infra: Infrastructure, links: LabelLinks | None = None) -> ServiceRuntime:
    saga_for = saga_factory(settings, infra)
    loops = infra.consumer_loops(build_registry(saga_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    idem = IdempotencyStore(infra.clock)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("schemas", SchemaReadiness(infra.serde, PRODUCED))
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))

    def retry_step(uow: UnitOfWork, row: Any) -> bool:
        return saga_for(uow).retry_step(uow, row)

    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            returns_router(infra.db, saga_for, links or links_from(settings, infra), infra.clock, auth, idem),
            saga_ops_router(db=infra.db, idempotency=idem, retry_step=retry_step, caller_of=ops_caller(auth)),
            dlq_router(dlq=infra.dlq_ops(), idempotency=idem, db=infra.db, auth=auth),
        ],
    )
    workers: list[Any] = [returns_deadline_sweeper(infra.db, saga_for, infra.clock, infra.metrics), infra.housekeeping()]
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
    build(settings, Infrastructure.from_settings(settings)).run()


if __name__ == "__main__":
    main()
