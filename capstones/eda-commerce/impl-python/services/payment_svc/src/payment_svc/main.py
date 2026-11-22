"""Composition root of payment-svc: ``payment-svc [serve|migrate]``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from contracts_py import records as R
from edacommon.db import UnitOfWork
from edacommon.http import Authenticator, Readiness, create_app, dlq_router
from edacommon.idempotency import IdempotencyStore
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, PeriodicTask, SchemaReadiness, ServiceRuntime
from edacommon.webhooks import WebhookReceiver
from sqlalchemy.orm import Session

from payment_svc.adapters.inbound.http.routes import fake_psp_router, webhook_router
from payment_svc.adapters.inbound.jobs.workers import Reconciler, WebhookProcessor
from payment_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from payment_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlPaymentRepository, WebhookStore
from payment_svc.adapters.outbound.psp.fake.psp import FakePsp, FakePspConfig, WebhookSender
from payment_svc.application.payments import Payments
from payment_svc.application.ports import PspGateway
from payment_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"


def fake_psp_from(settings: Settings, sender: WebhookSender | None = None) -> FakePsp:
    cfg = FakePspConfig(
        declineRate=settings.fake_psp_decline_rate,
        timeoutRate=settings.fake_psp_timeout_rate,
        duplicateWebhookRate=settings.fake_psp_duplicate_webhook_rate,
        webhookDelayMs=settings.fake_psp_webhook_delay_ms,
        slowWebhookMs=settings.fake_psp_slow_webhook_ms,
        apiLatencyMs=settings.fake_psp_api_latency_ms,
    )
    return FakePsp(cfg, sender or WebhookSender(settings.psp_webhook_url, settings.psp_webhook_secret))


@dataclass
class Wiring:
    payments_for: Callable[[UnitOfWork], Payments]
    receiver: WebhookReceiver
    processor: WebhookProcessor
    reconciler: Reconciler


def wire(settings: Settings, infra: Infrastructure, psp: PspGateway) -> Wiring:
    def payments_for(uow: UnitOfWork) -> Payments:
        return Payments(repo=SqlPaymentRepository(uow.session), psp=psp, events=OutboxPublisher(uow.session, infra.outbox))

    processor = WebhookProcessor(infra.db, payments_for, infra.clock)

    def store(session: Session, payload: dict[str, Any], raw: bytes) -> None:
        WebhookStore(session).store(payload)

    receiver = WebhookReceiver(
        db=infra.db,
        source="psp",
        consumer="psp-webhook",
        secret=settings.psp_webhook_secret,
        metrics=infra.metrics,
        event_id_of=lambda p: str(p["pspEventId"]),
        event_type_of=lambda p: str(p["eventType"]),
        store=store,
        on_stored=processor.wake,
    )
    return Wiring(payments_for, receiver, processor, Reconciler(infra.db, payments_for, infra.clock))


def build(settings: Settings, infra: Infrastructure) -> ServiceRuntime:
    psp = fake_psp_from(settings)
    w = wire(settings, infra, psp)
    loops = infra.consumer_loops(build_registry(w.payments_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add(
        "schemas",
        SchemaReadiness(
            infra.serde,
            [
                R.PaymentAuthorized,
                R.PaymentDeclined,
                R.PaymentCaptured,
                R.PaymentCaptureFailed,
                R.PaymentVoided,
                R.RefundSucceeded,
                R.RefundFailed,
            ],
        ),
    )
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[
            webhook_router(w.receiver, infra.clock),
            fake_psp_router(psp, auth),
            dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth),
        ],
    )
    sender = psp._sender
    workers: list[Any] = [
        w.processor,
        PeriodicTask("psp-reconciliation", w.reconciler.run_once, timedelta(seconds=5)),
        sender,
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
