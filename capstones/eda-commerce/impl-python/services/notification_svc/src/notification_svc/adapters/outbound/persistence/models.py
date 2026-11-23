"""SQLAlchemy 2 mapped classes for notification-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ContactRow(Base):
    __tablename__ = "contact"
    customer_id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class OrderContactRow(Base):
    __tablename__ = "order_contact"
    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class NotificationRow(Base):
    __tablename__ = "notification"
    notification_id: Mapped[str] = mapped_column(Text, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    order_id: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_type: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
