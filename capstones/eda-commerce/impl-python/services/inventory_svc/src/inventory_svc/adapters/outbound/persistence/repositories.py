"""Postgres implementation of :class:`InventoryRepository`.

The stock invariant lives in SQL (architecture §9): ``UPDATE stock SET reserved = reserved + :q
WHERE sku = :s AND on_hand - reserved >= :q``. A multi-line reservation runs inside a SAVEPOINT and
rolls back to it if any line is short, so reservations are all-or-nothing per order.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from inventory_svc.adapters.outbound.persistence.models import ReservationLineRow, ReservationRow, RestockRow, StockRow
from inventory_svc.domain.model import Reservation, ReservationStatus, Shortage, StockLevel, StockLine


class SqlInventoryRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_reservation(self, reservation_id: str, *, for_update: bool = False) -> Reservation | None:
        q = select(ReservationRow).where(ReservationRow.reservation_id == reservation_id)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        return self._to_domain(row) if row else None

    def _to_domain(self, row: ReservationRow) -> Reservation:
        lines = (
            self._s.execute(
                select(ReservationLineRow)
                .where(ReservationLineRow.reservation_id == row.reservation_id)
                .order_by(ReservationLineRow.sku)
            )
            .scalars()
            .all()
        )
        return Reservation(
            reservation_id=row.reservation_id,
            order_id=row.order_id,
            status=ReservationStatus(row.status),
            lines=tuple(StockLine(line.sku, line.quantity) for line in lines),
            expires_at=row.expires_at,
            shortages=tuple(Shortage(**s) for s in row.shortages),
            reason=row.reason,
            changed_at=row.changed_at,
        )

    def save_reservation(self, res: Reservation, now: datetime) -> None:
        values: dict[str, Any] = {
            "reservation_id": res.reservation_id,
            "order_id": res.order_id,
            "status": res.status.value,
            "expires_at": res.expires_at,
            "reason": res.reason,
            "changed_at": res.changed_at,
            "updated_at": now,
            "shortages": [{"sku": s.sku, "requested": s.requested, "available": s.available} for s in res.shortages],
        }
        stmt = pg_insert(ReservationRow).values(created_at=now, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["reservation_id"], set_={k: stmt.excluded[k] for k in values if k != "reservation_id"}
        )
        self._s.execute(stmt)
        exists = self._s.execute(
            select(ReservationLineRow.sku).where(ReservationLineRow.reservation_id == res.reservation_id).limit(1)
        ).first()
        if not exists and res.lines:
            self._s.execute(
                pg_insert(ReservationLineRow).values(
                    [{"reservation_id": res.reservation_id, "sku": line.sku, "quantity": line.quantity} for line in res.lines]
                )
            )

    def try_hold(self, lines: tuple[StockLine, ...]) -> list[Shortage]:
        sp = self._s.begin_nested()
        short = False
        for line in lines:  # sorted by sku: consistent lock order
            res = self._s.execute(
                text(
                    "UPDATE stock SET reserved = reserved + :q, version = version + 1, updated_at = now() "
                    "WHERE sku = :s AND on_hand - reserved >= :q"
                ),
                {"q": line.quantity, "s": line.sku},
            )
            if res.rowcount != 1:  # type: ignore[attr-defined]
                short = True
                break
        if not short:
            sp.commit()
            return []
        sp.rollback()
        levels = {lv.sku: lv for lv in self.levels([line.sku for line in lines])}
        return [
            Shortage(line.sku, line.quantity, levels[line.sku].available if line.sku in levels else 0)
            for line in lines
            if line.sku not in levels or levels[line.sku].available < line.quantity
        ]

    def _bump(self, sql: str, lines: tuple[StockLine, ...]) -> None:
        for line in lines:
            self._s.execute(text(sql), {"q": line.quantity, "s": line.sku})

    def release_held(self, lines: tuple[StockLine, ...]) -> None:
        self._bump(
            "UPDATE stock SET reserved = greatest(reserved - :q, 0), version = version + 1, updated_at = now() WHERE sku = :s",
            lines,
        )

    def allocate(self, lines: tuple[StockLine, ...]) -> None:
        self._bump(
            "UPDATE stock SET on_hand = on_hand - :q, reserved = greatest(reserved - :q, 0), "
            "version = version + 1, updated_at = now() WHERE sku = :s",
            lines,
        )

    def return_allocated(self, lines: tuple[StockLine, ...]) -> None:
        self._bump("UPDATE stock SET on_hand = on_hand + :q, version = version + 1, updated_at = now() WHERE sku = :s", lines)

    def add_on_hand(self, lines: tuple[StockLine, ...]) -> None:
        for line in lines:
            stmt = pg_insert(StockRow).values(sku=line.sku, on_hand=line.quantity, reserved=0, version=1)
            self._s.execute(
                stmt.on_conflict_do_update(
                    index_elements=["sku"],
                    set_={
                        "on_hand": StockRow.on_hand + line.quantity,
                        "version": StockRow.version + 1,
                        "updated_at": text("now()"),
                    },
                )
            )

    def set_on_hand(self, sku: str, on_hand: int) -> None:
        stmt = pg_insert(StockRow).values(sku=sku, on_hand=on_hand, reserved=0, version=1)
        self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["sku"], set_={"on_hand": on_hand, "version": StockRow.version + 1, "updated_at": text("now()")}
            )
        )

    def levels(self, skus: list[str]) -> list[StockLevel]:
        rows = self._s.execute(select(StockRow).where(StockRow.sku.in_(sorted(set(skus)))).order_by(StockRow.sku)).scalars()
        return [StockLevel(r.sku, r.on_hand, r.reserved, r.version) for r in rows]

    def due_expiries(self, now: datetime, limit: int) -> list[Reservation]:
        rows = (
            self._s.execute(
                select(ReservationRow)
                .where(ReservationRow.status == ReservationStatus.HELD.value, ReservationRow.expires_at <= now)
                .order_by(ReservationRow.expires_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        return [self._to_domain(r) for r in rows]

    def restock_seen(self, restock_id: str) -> tuple[StockLine, ...] | None:
        row = self._s.get(RestockRow, restock_id)
        if row is None:
            return None
        return tuple(StockLine(x["sku"], int(x["quantity"])) for x in row.lines)

    def record_restock(self, restock_id: str, order_id: str, return_id: str, lines: tuple[StockLine, ...], now: datetime) -> None:
        self._s.add(
            RestockRow(
                restock_id=restock_id,
                order_id=order_id,
                return_id=return_id,
                lines=[{"sku": x.sku, "quantity": x.quantity} for x in lines],
                restocked_at=now,
            )
        )
        self._s.flush()

    def delete_all(self) -> None:  # tests only
        for model in (ReservationLineRow, ReservationRow, RestockRow, StockRow):
            self._s.execute(delete(model))

    def stock(self, sku: str) -> StockLevel | None:
        r = self._s.get(StockRow, sku, populate_existing=True)
        return StockLevel(r.sku, r.on_hand, r.reserved, r.version) if r else None


class OutboxPublisher:
    """EventPublisher port on top of the shared OutboxWriter (same transaction)."""

    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
