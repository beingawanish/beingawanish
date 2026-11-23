"""SQLAlchemy 2 mapped classes for inventory-svc's private tables (migration 0002)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class StockRow(Base):
    __tablename__ = "stock"
    sku: Mapped[str] = mapped_column(Text, primary_key=True)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ReservationRow(Base):
    __tablename__ = "reservation"
    reservation_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shortages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class ReservationLineRow(Base):
    __tablename__ = "reservation_line"
    reservation_id: Mapped[str] = mapped_column(Text, ForeignKey("reservation.reservation_id"), primary_key=True)
    sku: Mapped[str] = mapped_column(Text, primary_key=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)


class RestockRow(Base):
    __tablename__ = "restock"
    restock_id: Mapped[str] = mapped_column(Text, primary_key=True)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    return_id: Mapped[str] = mapped_column(Text, nullable=False)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    restocked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
