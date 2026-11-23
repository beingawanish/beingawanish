"""Ports of notification-svc. The mailer port is implemented by the fake mail gateway today and by a
real email/SMS provider tomorrow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from edacommon.envelope import OutgoingMessage


@dataclass(frozen=True, slots=True)
class Contact:
    customer_id: str
    email: str
    name: str | None


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Email:
    to: str
    subject: str
    text: str
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True, slots=True)
class SentNotification:
    notification_id: str
    dedupe_key: str
    order_id: str | None
    customer_id: str
    channel: str
    template: str
    source_event_id: str
    source_event_type: str
    attachment_count: int
    provider_message_id: str
    sent_at: datetime


class Mailer(Protocol):
    def send(self, email: Email, *, idempotency_key: str) -> str:
        """Send once per idempotency key (a retry after a rollback is a no-op at the gateway).
        Returns the provider's message id."""
        ...


class AttachmentStore(Protocol):
    def get(self, claim_check: dict[str, Any]) -> bytes:
        """Download and verify size + SHA-256 (ADR-0009). Missing -> RetryLater."""
        ...


class NotificationRepository(Protocol):
    def upsert_contact(self, order_id: str, contact: Contact, now: datetime) -> None: ...

    def contact_for_order(self, order_id: str) -> Contact | None: ...

    def already_sent(self, dedupe_key: str) -> bool: ...

    def record(self, n: SentNotification) -> None: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...
