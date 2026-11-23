"""SQLAlchemy 2 mapped classes for payment-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaymentRow(Base):
    __tablename__ = "payment"
    payment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    psp_payment_id: Mapped[str | None] = mapped_column(Text)
    psp_reference: Mapped[str | None] = mapped_column(Text)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    capture_failure: Mapped[str | None] = mapped_column(Text)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capture_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unknown_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_reconcile_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late_success_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    last_command_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class PaymentAttemptRow(Base):
    __tablename__ = "payment_attempt"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefundRow(Base):
    __tablename__ = "refund"
    refund_id: Mapped[str] = mapped_column(Text, primary_key=True)
    payment_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    return_id: Mapped[str | None] = mapped_column(Text)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    psp_reference: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_command_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class PspWebhookRow(Base):
    __tablename__ = "psp_webhook"
    psp_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_reference: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
