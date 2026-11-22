"""SQLAlchemy 2 mapped classes for returns-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EligibilityViewRow(Base):
    __tablename__ = "eligibility_view"
    order_id: Mapped[str] = mapped_column(Text, primary_key=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    shipping_fee_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    ship_to: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payment_id: Mapped[str | None] = mapped_column(Text)
    warehouse_id: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    shipping_fee_return_id: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ReturnRequestRow(Base):
    __tablename__ = "return_request"
    return_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, ForeignKey("eligibility_view.order_id"), nullable=False)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    rma_number: Mapped[str | None] = mapped_column(Text, unique=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    refund_minor: Mapped[int | None] = mapped_column(BigInteger)
    refund_id: Mapped[str | None] = mapped_column(Text, unique=True)
    label: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    parcel_due_by: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    counts_against_order: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ReturnLineRow(Base):
    __tablename__ = "return_line"
    return_id: Mapped[str] = mapped_column(Text, ForeignKey("return_request.return_id"), primary_key=True)
    line_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sku: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    inspection: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)


class RmaCounterRow(Base):
    __tablename__ = "rma_counter"
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
