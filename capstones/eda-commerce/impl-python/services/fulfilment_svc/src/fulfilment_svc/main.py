"""Composition root of fulfilment-svc: ``fulfilment-svc [serve|migrate]``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.db import UnitOfWork
from edacommon.http import Authenticator, Readiness, create_app, dlq_router
from edacommon.idempotency import IdempotencyStore
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, PeriodicTask, SchemaReadiness, ServiceRuntime

from fulfilment_svc.adapters.inbound.http.routes import fake_wms_router
from fulfilment_svc.adapters.inbound.jobs.warehouse import WarehouseEventPump
from fulfilment_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from fulfilment_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlFulfilmentRepository
from fulfilment_svc.adapters.outbound.storage.manifests import ClaimCheckManifests
from fulfilment_svc.adapters.outbound.wms.fake.wms import FakeWms, FakeWmsConfig
from fulfilment_svc.application.ports import ManifestStore, Warehouse
from fulfilment_svc.application.use_cases import Fulfilments
from fulfilment_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"
PRODUCED = [
    R.FulfilmentAccepted,
    R.OrderPicked,
    R.OrderPacked,
    R.OrderDispatched,
    R.FulfilmentCancelled,
    R.FulfilmentFailed,
    R.ReturnReceived,
    R.ReturnInspected,
]


def fake_wms_from(settings: Settings, seed: int | None = None) -> FakeWms:
    return FakeWms(
        FakeWmsConfig(
            dropRequestRate=settings.fake_wms_drop_request_rate,
            acceptDelayMs=settings.fake_wms_accept_delay_ms,
            pickDelayMs=settings.fake_wms_pick_delay_ms,
            packDelayMs=settings.fake_wms_pack_delay_ms,
            failRate=settings.fake_wms_fail_rate,
            manifestLines=settings.fake_wms_manifest_lines,
            inspectionDamagedRate=settings.fake_wms_inspection_damaged_rate,
        ),
        seed=seed,
    )


def manifests_from(settings: Settings, infra: Infrastructure) -> ManifestStore:
    return ClaimCheckManifests(
        ClaimCheckStore.from_settings(
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            metrics=infra.metrics,
        )
    )


def fulfilments_factory(
    infra: Infrastructure, warehouse: Warehouse, manifests: ManifestStore
) -> Callable[[UnitOfWork], Fulfilments]:
    def make(uow: UnitOfWork) -> Fulfilments:
        return Fulfilments(
            repo=SqlFulfilmentRepository(uow.session),
            warehouse=warehouse,
            manifests=manifests,
            events=OutboxPublisher(uow.session, infra.outbox),
        )

    return make


def build(settings: Settings, infra: Infrastructure, manifests: ManifestStore | None = None) -> ServiceRuntime:
    wms = fake_wms_from(settings)
    fulfilments_for = fulfilments_factory(infra, wms, manifests or manifests_from(settings, infra))
    loops = infra.consumer_loops(build_registry(fulfilments_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("schemas", SchemaReadiness(infra.serde, PRODUCED))
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            fake_wms_router(wms, auth),
            dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth),
        ],
    )
    pump = WarehouseEventPump(infra.db, wms, fulfilments_for, infra.clock)
    workers: list[Any] = [PeriodicTask("wms-events", pump.run_once, timedelta(milliseconds=500)), infra.housekeeping()]
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
