"""SQLAlchemy 2 mapped classes for fulfilment-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FulfilmentRow(Base):
    __tablename__ = "fulfilment"
    fulfilment_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    ship_to: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    shipping_method: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'STANDARD'"))
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    wms_submissions: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    warehouse_id: Mapped[str | None] = mapped_column(Text)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_dispatch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    packed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    shipment_id: Mapped[str | None] = mapped_column(Text)
    last_command_id: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ParcelRow(Base):
    __tablename__ = "parcel"
    parcel_id: Mapped[str] = mapped_column(Text, primary_key=True)
    fulfilment_id: Mapped[str] = mapped_column(Text, ForeignKey("fulfilment.fulfilment_id"), nullable=False)
    weight_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    length_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    width_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    height_mm: Mapped[int] = mapped_column(Integer, nullable=False)


class ReturnIntakeRow(Base):
    __tablename__ = "return_intake"
    return_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    rma_number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    expected_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shipment_id: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_event_id: Mapped[str | None] = mapped_column(Text)
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
