"""Composition root of shipping-svc: ``shipping-svc [serve|migrate]``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.db import UnitOfWork
from edacommon.http import Authenticator, Readiness, create_app, dlq_router
from edacommon.idempotency import IdempotencyStore
from edacommon.ids import new_id
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, PeriodicTask, SchemaReadiness, ServiceRuntime
from edacommon.webhooks import WebhookReceiver
from sqlalchemy.orm import Session

from shipping_svc.adapters.inbound.http.routes import fake_carrier_router, webhook_router
from shipping_svc.adapters.inbound.jobs.workers import BookingRetrier, TrackingProcessor
from shipping_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from shipping_svc.adapters.outbound.carrier.acl import validate
from shipping_svc.adapters.outbound.carrier.fake.carrier import FakeCarrier, FakeCarrierConfig
from shipping_svc.adapters.outbound.documents.label_pdf import FpdfLabelRenderer
from shipping_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlShipmentRepository, TrackingEventStore
from shipping_svc.adapters.outbound.storage.labels import ClaimCheckLabels
from shipping_svc.application.ports import Carrier, LabelStore
from shipping_svc.application.use_cases import Shipments
from shipping_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"
PRODUCED = [R.ShipmentCreated, R.ShipmentInTransit, R.ShipmentDelivered, R.ShipmentException]


def fake_carrier_from(settings: Settings, **kw: Any) -> FakeCarrier:
    cfg = FakeCarrierConfig(
        duplicateRate=settings.fake_carrier_duplicate_rate,
        outOfOrderRate=settings.fake_carrier_out_of_order_rate,
        exceptionRate=settings.fake_carrier_exception_rate,
        stepDelayMs=settings.fake_carrier_step_delay_ms,
        bookingFailureRate=settings.fake_carrier_booking_failure_rate,
    )
    return FakeCarrier(cfg, url=settings.carrier_webhook_url, secret=settings.carrier_webhook_secret, **kw)


def labels_from(settings: Settings, infra: Infrastructure) -> LabelStore:
    return ClaimCheckLabels(
        ClaimCheckStore.from_settings(
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            metrics=infra.metrics,
        )
    )


@dataclass
class Wiring:
    shipments_for: Callable[[UnitOfWork], Shipments]
    receiver: WebhookReceiver
    tracking: TrackingProcessor
    bookings: BookingRetrier


def wire(settings: Settings, infra: Infrastructure, carrier: Carrier, labels: LabelStore) -> Wiring:
    renderer = FpdfLabelRenderer()

    def shipments_for(uow: UnitOfWork) -> Shipments:
        return Shipments(
            repo=SqlShipmentRepository(uow.session),
            carrier=carrier,
            renderer=renderer,
            labels=labels,
            events=OutboxPublisher(uow.session, infra.outbox),
            mint=new_id,
        )

    tracking = TrackingProcessor(infra.db, shipments_for, infra.clock)

    def store(session: Session, payload: dict[str, Any], raw: bytes) -> None:
        TrackingEventStore(session).store(payload, infra.clock.now())

    receiver = WebhookReceiver(
        db=infra.db,
        source="carrier",
        consumer="carrier-webhook",
        secret=settings.carrier_webhook_secret,
        metrics=infra.metrics,
        event_id_of=lambda p: str(p["carrierEventId"]),
        event_type_of=validate,
        store=store,
        on_stored=tracking.wake,
    )
    return Wiring(shipments_for, receiver, tracking, BookingRetrier(infra.db, shipments_for, infra.clock))


def build(settings: Settings, infra: Infrastructure, labels: LabelStore | None = None) -> ServiceRuntime:
    carrier = fake_carrier_from(settings)
    w = wire(settings, infra, carrier, labels or labels_from(settings, infra))
    loops = infra.consumer_loops(build_registry(w.shipments_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("schemas", SchemaReadiness(infra.serde, PRODUCED))
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            webhook_router(w.receiver, infra.clock),
            fake_carrier_router(carrier, auth),
            dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth),
        ],
    )
    workers: list[Any] = [
        w.tracking,
        PeriodicTask("booking-retries", w.bookings.run_once, timedelta(seconds=5)),
        carrier,
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
    build(settings, Infrastructure.from_settings(settings)).run()


if __name__ == "__main__":
    main()
