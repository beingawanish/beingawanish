"""Postgres implementation of :class:`ReturnsRepository`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from returns_svc.adapters.outbound.persistence.models import EligibilityViewRow, ReturnLineRow, ReturnRequestRow, RmaCounterRow
from returns_svc.application.ports import ReturnRecord, StoredLine
from returns_svc.domain.policy import OrderLine, OrderView

_FACTS = frozenset({"payment_id", "warehouse_id", "delivered_at", "cancelled"})


def _claim_to_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": exp.isoformat() if isinstance(exp, datetime) else exp}


def _claim_from_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": datetime.fromisoformat(exp) if isinstance(exp, str) else exp}


class SqlReturnsRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ------------------------------------------------------------------- eligibility view
    def view(self, order_id: str, *, for_update: bool = False) -> OrderView | None:
        q = select(EligibilityViewRow).where(EligibilityViewRow.order_id == order_id)
        if for_update:
            q = q.with_for_update()
        r = self._s.execute(q).scalar_one_or_none()
        if r is None:
            return None
        return OrderView(
            order_id=r.order_id,
            customer_id=r.customer_id,
            currency=r.currency,
            total_minor=r.total_minor,
            lines=tuple(OrderLine(**x) for x in r.lines),
            shipping_fee_minor=r.shipping_fee_minor,
            ship_to=r.ship_to,
            payment_id=r.payment_id,
            warehouse_id=r.warehouse_id,
            delivered_at=r.delivered_at,
            cancelled=r.cancelled,
            shipping_fee_return_id=r.shipping_fee_return_id,
        )

    def placed(
        self,
        *,
        order_id: str,
        customer_id: str,
        currency: str,
        total_minor: int,
        shipping_fee_minor: int,
        lines: tuple[OrderLine, ...],
        ship_to: dict[str, Any],
        now: datetime,
    ) -> None:
        values = {
            "customer_id": customer_id,
            "currency": currency,
            "total_minor": total_minor,
            "shipping_fee_minor": shipping_fee_minor,
            "lines": [
                {
                    "line_id": x.line_id,
                    "sku": x.sku,
                    "product_name": x.product_name,
                    "quantity": x.quantity,
                    "unit_price_minor": x.unit_price_minor,
                    "line_total_minor": x.line_total_minor,
                }
                for x in lines
            ],
            "ship_to": ship_to,
            "updated_at": now,
        }
        stmt = pg_insert(EligibilityViewRow).values(order_id=order_id, **values)
        # OrderPlaced is a full snapshot of the order: last write wins on its own columns only.
        self._s.execute(stmt.on_conflict_do_update(index_elements=["order_id"], set_={k: stmt.excluded[k] for k in values}))

    def set_view_fact(self, order_id: str, now: datetime, **facts: Any) -> bool:
        unknown = set(facts) - _FACTS
        if unknown:
            raise ValueError(f"not a view fact: {sorted(unknown)}")
        res = self._s.execute(
            update(EligibilityViewRow).where(EligibilityViewRow.order_id == order_id).values(updated_at=now, **facts)
        )
        return bool(res.rowcount)  # type: ignore[attr-defined]

    def claim_shipping_fee(self, order_id: str, return_id: str) -> None:
        self._s.execute(
            update(EligibilityViewRow)
            .where(EligibilityViewRow.order_id == order_id, EligibilityViewRow.shipping_fee_return_id.is_(None))
            .values(shipping_fee_return_id=return_id)
        )

    # --------------------------------------------------------------------------- returns
    def returned_quantities(self, order_id: str) -> dict[str, int]:
        rows = self._s.execute(
            select(ReturnLineRow.line_id, func.sum(ReturnLineRow.quantity))
            .join(ReturnRequestRow, ReturnRequestRow.return_id == ReturnLineRow.return_id)
            .where(ReturnRequestRow.order_id == order_id, ReturnRequestRow.counts_against_order.is_(True))
            .group_by(ReturnLineRow.line_id)
        ).all()
        return {str(a): int(b) for a, b in rows}

    def _values(self, r: ReturnRecord, now: datetime) -> dict[str, Any]:
        return {
            "order_id": r.order_id,
            "customer_id": r.customer_id,
            "reason": r.reason,
            "comment": r.comment,
            "status": r.status,
            "rma_number": r.rma_number,
            "currency": r.currency,
            "refund_minor": r.refund_minor,
            "refund_id": r.refund_id,
            "label": _claim_to_json(r.label),
            "parcel_due_by": r.parcel_due_by,
            "counts_against_order": r.counts_against_order,
            "requested_at": r.requested_at,
            "updated_at": now,
        }

    def insert(self, r: ReturnRecord, now: datetime) -> None:
        self._s.execute(pg_insert(ReturnRequestRow).values(return_id=r.return_id, **self._values(r, now)))
        self._s.execute(
            pg_insert(ReturnLineRow).values(
                [
                    {
                        "return_id": r.return_id,
                        "line_id": x.line_id,
                        "sku": x.sku,
                        "quantity": x.quantity,
                        "unit_price_minor": x.unit_price_minor,
                    }
                    for x in r.lines
                ]
            )
        )

    def update(self, r: ReturnRecord, now: datetime) -> None:
        self._s.execute(update(ReturnRequestRow).where(ReturnRequestRow.return_id == r.return_id).values(**self._values(r, now)))
        for x in r.lines:
            self._s.execute(
                update(ReturnLineRow)
                .where(ReturnLineRow.return_id == r.return_id, ReturnLineRow.line_id == x.line_id)
                .values(inspection=list(x.inspection) or None)
            )

    def _record(self, row: ReturnRequestRow) -> ReturnRecord:
        lines = self._s.execute(
            select(ReturnLineRow).where(ReturnLineRow.return_id == row.return_id).order_by(ReturnLineRow.line_id)
        ).scalars()
        return ReturnRecord(
            return_id=row.return_id,
            order_id=row.order_id,
            customer_id=row.customer_id,
            reason=row.reason,
            comment=row.comment,
            status=row.status,
            currency=row.currency,
            requested_at=row.requested_at,
            lines=tuple(StoredLine(x.line_id, x.sku, x.quantity, x.unit_price_minor, tuple(x.inspection or ())) for x in lines),
            rma_number=row.rma_number,
            refund_minor=row.refund_minor,
            refund_id=row.refund_id,
            label=_claim_from_json(row.label),
            parcel_due_by=row.parcel_due_by,
            counts_against_order=row.counts_against_order,
        )

    def get(self, return_id: str) -> ReturnRecord | None:
        row = self._s.execute(
            select(ReturnRequestRow).where(ReturnRequestRow.return_id == return_id).execution_options(populate_existing=True)
        ).scalar_one_or_none()
        return self._record(row) if row else None

    def for_order(self, order_id: str) -> list[ReturnRecord]:
        rows = self._s.execute(
            select(ReturnRequestRow)
            .where(ReturnRequestRow.order_id == order_id)
            .order_by(ReturnRequestRow.requested_at, ReturnRequestRow.return_id)
        ).scalars()
        return [self._record(r) for r in rows]

    def return_id_for_refund(self, refund_id: str) -> str | None:
        return self._s.execute(
            select(ReturnRequestRow.return_id).where(ReturnRequestRow.refund_id == refund_id)
        ).scalar_one_or_none()

    def next_rma(self, year: int) -> int:
        self._s.execute(pg_insert(RmaCounterRow).values(year=year, last_seq=0).on_conflict_do_nothing(index_elements=["year"]))
        row = self._s.execute(select(RmaCounterRow).where(RmaCounterRow.year == year).with_for_update()).scalar_one()
        row.last_seq += 1
        self._s.flush()
        return int(row.last_seq)
