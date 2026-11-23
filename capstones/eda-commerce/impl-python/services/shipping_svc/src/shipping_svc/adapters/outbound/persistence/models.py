"""SQLAlchemy 2 mapped classes for shipping-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ShipmentRow(Base):
    __tablename__ = "shipment"
    shipment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(Text, nullable=False)
    fulfilment_id: Mapped[str | None] = mapped_column(Text, unique=True)
    return_id: Mapped[str | None] = mapped_column(Text, unique=True)
    warehouse_id: Mapped[str | None] = mapped_column(Text)
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parcel_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    shipping_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'STANDARD'"))
    status: Mapped[str] = mapped_column(Text, nullable=False)
    carrier: Mapped[str | None] = mapped_column(Text)
    tracking_number: Mapped[str | None] = mapped_column(Text, unique=True)
    label: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    booking_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    causation_id: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class TrackingEventRow(Base):
    __tablename__ = "tracking_event"
    carrier_event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tracking_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    exception_code: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    shipment_id: Mapped[str | None] = mapped_column(Text)
