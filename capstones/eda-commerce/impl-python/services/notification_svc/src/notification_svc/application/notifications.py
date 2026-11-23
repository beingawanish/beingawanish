"""Choreographed reactions (ADR-0001): every handled event becomes at most one customer message.

One transaction per triggering event: dedupe check -> attachments fetched and verified -> send ->
``notification`` row + ``NotificationSent`` in the outbox. The send is a side effect outside the
transaction; it is made safe by the gateway idempotency key (= the dedupe key), so a rollback after a
successful send and the redelivery that follows never send a second email (ADR-0006 layer 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from contracts_py.records import NotificationSent
from edacommon.envelope import OutgoingMessage
from edacommon.errors import RetryLater
from edacommon.ids import new_id
from edacommon.logging import get_logger

from notification_svc.application.ports import (
    Attachment,
    AttachmentStore,
    Contact,
    Email,
    EventPublisher,
    Mailer,
    NotificationRepository,
    SentNotification,
)
from notification_svc.domain.templates import Notice, render

log = get_logger(__name__)
CHANNEL = "EMAIL"


@dataclass
class Notifications:
    repo: NotificationRepository
    mailer: Mailer
    attachments: AttachmentStore
    events: EventPublisher

    def record_contact(self, *, order_id: str, customer_id: str, email: str, name: str | None, now: datetime) -> None:
        self.repo.upsert_contact(order_id, Contact(customer_id, email, name), now)

    def notify(self, notice: Notice, *, source_event_id: str, source_event_type: str, now: datetime) -> bool:
        """False when this business event was already notified (a re-emitted fact)."""
        if self.repo.already_sent(notice.dedupe_key):
            log.info("notification already sent", template=notice.template, order_id=notice.order_id)
            return False
        contact = self.repo.contact_for_order(notice.order_id)
        if contact is None:
            # OrderPlaced is on order.events.v1; this event may come from another topic and be early.
            raise RetryLater(f"no contact for order {notice.order_id} yet")
        files = tuple(f for cc in notice.attachments if (f := self._fetch(cc, now)) is not None)
        rendered = render(notice, contact.name)
        message_id = self.mailer.send(
            Email(to=contact.email, subject=rendered.subject, text=rendered.text, attachments=files),
            idempotency_key=notice.dedupe_key,
        )
        sent = SentNotification(
            notification_id=new_id(),
            dedupe_key=notice.dedupe_key,
            order_id=notice.order_id,
            customer_id=contact.customer_id,
            channel=CHANNEL,
            template=notice.template,
            source_event_id=source_event_id,
            source_event_type=source_event_type,
            attachment_count=len(files),
            provider_message_id=message_id,
            sent_at=now,
        )
        self.repo.record(sent)
        self.events.publish(_sent(sent))
        # Ids only: never the address, the name or the body (ADR-0013).
        log.info("notification sent", notification_id=sent.notification_id, template=sent.template, order_id=sent.order_id)
        return True

    def _fetch(self, cc: dict[str, Any], now: datetime) -> Attachment | None:
        exp = cc.get("expiresAt")
        if isinstance(exp, datetime) and exp < now:
            # ADR-0009: replaying an old event after its object expired is "skip with a warning".
            log.warning("attachment expired; sending without it", bucket=cc.get("bucket"))
            return None
        data = self.attachments.get(cc)
        name = str(cc["objectKey"]).rsplit("/", 1)[-1]
        return Attachment(name, str(cc["contentType"]), data)


def _sent(n: SentNotification) -> OutgoingMessage:
    # Key orderId; notifications without an order would use customerId (topics.yaml).
    return OutgoingMessage(
        topic=NotificationSent.TOPIC,
        record_type=NotificationSent.AVRO_NAME,
        key=n.order_id or n.customer_id,
        aggregate_type="Notification",
        aggregate_id=n.notification_id,
        aggregate_version=1,
        body={
            "notificationId": n.notification_id,
            "customerId": n.customer_id,
            "orderId": n.order_id,
            "channel": n.channel,
            "template": n.template,
            "sourceEventId": n.source_event_id,
            "sentAt": n.sent_at,
            "attachmentCount": n.attachment_count,
        },
    )
