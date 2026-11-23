"""Postgres implementation of :class:`NotificationRepository` and the outbox EventPublisher."""

from __future__ import annotations

from datetime import datetime

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from notification_svc.adapters.outbound.persistence.models import ContactRow, NotificationRow, OrderContactRow
from notification_svc.application.ports import Contact, SentNotification


class SqlNotificationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def upsert_contact(self, order_id: str, contact: Contact, now: datetime) -> None:
        stmt = pg_insert(ContactRow).values(
            customer_id=contact.customer_id, email=contact.email, name=contact.name, updated_at=now
        )
        self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["customer_id"], set_={"email": stmt.excluded.email, "name": stmt.excluded.name, "updated_at": now}
            )
        )
        # The order keeps the contact it was placed with, even if the customer changes it later.
        self._s.execute(
            pg_insert(OrderContactRow)
            .values(order_id=order_id, customer_id=contact.customer_id, email=contact.email, name=contact.name, created_at=now)
            .on_conflict_do_nothing(index_elements=["order_id"])
        )

    def contact_for_order(self, order_id: str) -> Contact | None:
        row = self._s.get(OrderContactRow, order_id)
        return Contact(row.customer_id, row.email, row.name) if row else None

    def already_sent(self, dedupe_key: str) -> bool:
        return (
            self._s.execute(select(NotificationRow.notification_id).where(NotificationRow.dedupe_key == dedupe_key)).first()
            is not None
        )

    def record(self, n: SentNotification) -> None:
        self._s.add(
            NotificationRow(
                notification_id=n.notification_id,
                dedupe_key=n.dedupe_key,
                order_id=n.order_id,
                customer_id=n.customer_id,
                channel=n.channel,
                template=n.template,
                source_event_id=n.source_event_id,
                source_event_type=n.source_event_type,
                attachment_count=n.attachment_count,
                provider_message_id=n.provider_message_id,
                sent_at=n.sent_at,
            )
        )
        self._s.flush()

    def sent_for_order(self, order_id: str) -> list[NotificationRow]:
        return list(
            self._s.execute(
                select(NotificationRow).where(NotificationRow.order_id == order_id).order_by(NotificationRow.sent_at)
            ).scalars()
        )


class OutboxPublisher:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
