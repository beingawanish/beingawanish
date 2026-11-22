"""Composition root of order-svc: ``order-svc [serve|projector|migrate]``.

``serve`` runs the saga (consumers, deadline sweeper, Orders API, ops). ``projector`` runs the
order-history projection as its own process and consumer group (ADR-0010); same image, different
argument (infra/compose.apps.example.yml).
"""

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

from order_svc.adapters.inbound.http.routes import ops_caller, orders_router
from order_svc.adapters.inbound.jobs.deadlines import order_deadline_sweeper
from order_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from order_svc.adapters.outbound.documents.pdf import FpdfInvoiceRenderer
from order_svc.adapters.outbound.documents.store import ClaimCheckDocuments
from order_svc.adapters.outbound.persistence.repositories import SqlInvoiceRepository, SqlOrderRepository
from order_svc.adapters.projector import projection
from order_svc.application.handle_saga_trigger import OrderSaga, Ports
from order_svc.application.ports import DocumentStore
from order_svc.config import Settings
from order_svc.domain.saga import SAGA_TYPE

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"


def saga_factory(settings: Settings, infra: Infrastructure, documents: DocumentStore) -> Callable[[UnitOfWork], OrderSaga]:
    engine = SagaEngine(saga_type=SAGA_TYPE, outbox=infra.outbox, metrics=infra.metrics, clock=infra.clock)
    renderer = FpdfInvoiceRenderer()
    timeouts = settings.timeouts()

    def ports_for(uow: UnitOfWork) -> Ports:
        return Ports(orders=SqlOrderRepository(uow.session), invoices=SqlInvoiceRepository(uow.session))

    saga = OrderSaga(engine=engine, ports_for=ports_for, renderer=renderer, documents=documents, timeouts=timeouts, mint=new_id)
    return lambda uow: saga


def documents_from(settings: Settings, infra: Infrastructure) -> DocumentStore:
    return ClaimCheckDocuments(
        ClaimCheckStore.from_settings(
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            metrics=infra.metrics,
        )
    )


def build(settings: Settings, infra: Infrastructure, documents: DocumentStore | None = None) -> ServiceRuntime:
    documents = documents or documents_from(settings, infra)
    saga_for = saga_factory(settings, infra, documents)
    loops = infra.consumer_loops(build_registry(saga_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    idem = IdempotencyStore(infra.clock)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add(
        "schemas",
        SchemaReadiness(
            infra.serde,
            [
                R.OrderPlaced,
                R.OrderConfirmed,
                R.OrderCancelled,
                R.OrderShipped,
                R.OrderDelivered,
                R.InvoiceIssued,
                R.OrderRequiresAttention,
                R.ReserveStock,
                R.CommitReservation,
                R.ReleaseReservation,
                R.AuthorizePayment,
                R.CapturePayment,
                R.VoidPayment,
                R.RequestFulfilment,
                R.CancelFulfilment,
            ],
        ),
    )
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))

    def retry_step(uow: UnitOfWork, row: Any) -> bool:
        return saga_for(uow).retry_step(uow, row)

    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            orders_router(infra.db, documents, auth),
            saga_ops_router(db=infra.db, idempotency=idem, retry_step=retry_step, caller_of=ops_caller(auth)),
            dlq_router(dlq=infra.dlq_ops(), idempotency=idem, db=infra.db, auth=auth),
        ],
    )
    workers: list[Any] = [order_deadline_sweeper(infra.db, saga_for, infra.clock, infra.metrics), infra.housekeeping()]
    relay = infra.relay()
    if relay:
        workers.append(relay)
    return ServiceRuntime(
        settings=settings, app=app, loops=loops, workers=workers, on_shutdown=[lambda: infra.producer.flush(5), infra.db.dispose]
    )


def build_projector(settings: Settings, infra: Infrastructure) -> ServiceRuntime:
    """The projector writes no outbox rows; it only needs consumers, health and DLQ ops."""
    loops = infra.consumer_loops(projection.build_registry(), projection.TOPICS)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    auth = Authenticator(settings)
    app = create_app(
        settings,
        readiness=readiness,
        routers=[dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth)],
    )
    return ServiceRuntime(settings=settings, app=app, loops=loops, workers=[], on_shutdown=[infra.db.dispose])


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    cmd = args[0] if args else "serve"
    settings = Settings()
    if cmd == "projector" and settings.service_name == "order-svc":
        # Not configured explicitly (compose sets SERVICE_NAME/CONSUMER_GROUP): use the contract's group.
        settings = settings.model_copy(update={"service_name": projection.GROUP, "consumer_group": projection.GROUP})
    migrate(MIGRATIONS, settings.db_url)
    if cmd == "migrate":
        return
    infra = Infrastructure.from_settings(settings)
    (build_projector if cmd == "projector" else build)(settings, infra).run()


if __name__ == "__main__":
    main()
