"""Composition root of notification-svc: ``notification-svc [serve|migrate]``."""

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
from edacommon.migrations.runner import migrate
from edacommon.runtime import Infrastructure, SchemaReadiness, ServiceRuntime

from notification_svc.adapters.inbound.messaging.handlers import TOPICS, build_registry
from notification_svc.adapters.outbound.mail.fake.mailer import FakeMailer
from notification_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlNotificationRepository
from notification_svc.adapters.outbound.storage.attachments import ClaimCheckAttachments
from notification_svc.application.notifications import Notifications
from notification_svc.application.ports import AttachmentStore, Mailer
from notification_svc.config import Settings

_PACKAGED = Path(__file__).resolve().parent / "_migrations"
MIGRATIONS = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "migrations"


def attachments_from(settings: Settings, infra: Infrastructure) -> AttachmentStore:
    return ClaimCheckAttachments(
        ClaimCheckStore.from_settings(
            endpoint=settings.s3_endpoint,
            region=settings.s3_region,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            metrics=infra.metrics,
        )
    )


def notifications_factory(
    infra: Infrastructure, mailer: Mailer, attachments: AttachmentStore
) -> Callable[[UnitOfWork], Notifications]:
    def make(uow: UnitOfWork) -> Notifications:
        return Notifications(
            repo=SqlNotificationRepository(uow.session),
            mailer=mailer,
            attachments=attachments,
            events=OutboxPublisher(uow.session, infra.outbox),
        )

    return make


def build(settings: Settings, infra: Infrastructure, attachments: AttachmentStore | None = None) -> ServiceRuntime:
    notifications_for = notifications_factory(infra, FakeMailer(), attachments or attachments_from(settings, infra))
    loops = infra.consumer_loops(build_registry(notifications_for, infra.clock), TOPICS)
    auth = Authenticator(settings)
    readiness = Readiness()
    readiness.add("database", infra.db.ping)
    readiness.add("schemas", SchemaReadiness(infra.serde, [R.NotificationSent]))
    readiness.add("consumer", lambda: all(lp.subscribed.is_set() for lp in loops))
    app = create_app(
        settings,
        readiness=readiness,
        routers=[dlq_router(dlq=infra.dlq_ops(), idempotency=IdempotencyStore(infra.clock), db=infra.db, auth=auth)],
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
    cmd = args[0] if args else "serve"
    settings = Settings()
    migrate(MIGRATIONS, settings.db_url)
    if cmd == "migrate":
        return
    build(settings, Infrastructure.from_settings(settings)).run()


if __name__ == "__main__":
    main()
