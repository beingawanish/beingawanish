"""Postgres implementations of OrderRepository and InvoiceRepository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from edacommon.ids import from_millis
from order_svc.adapters.outbound.persistence.models import InvoiceRow, OrderLineRow, OrderRow
from order_svc.application.ports import OrderRecord, StoredInvoice


def _jsonable(d: Any) -> Any:
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, dict):
        return {k: _jsonable(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_jsonable(v) for v in d]
    return d


class SqlOrderRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, o: OrderRecord) -> None:
        self._s.add(OrderRow(order_id=o.order_id, customer_id=o.customer_id, status=o.status, total_minor=o.total_minor,
                             currency=o.currency, placed_at=o.placed_at, version=o.version, contact_email=o.contact_email,
                             ship_to=o.ship_to, shipping_method=o.shipping_method))
        self._s.flush()
        for i, line in enumerate(o.lines):
            self._s.add(OrderLineRow(order_id=o.order_id, line_id=line["lineId"], position=i, sku=line["sku"],
                                     product_name=line["productName"], quantity=int(line["quantity"]),
                                     unit_price_minor=int(line["unitPrice"]["amountMinor"]),
                                     line_total_minor=int(line["lineTotal"]["amountMinor"])))
        self._s.flush()

    def get(self, order_id: str) -> OrderRecord | None:
        row = self._s.get(OrderRow, order_id)
        if row is None:
            return None
        lines = self._s.execute(select(OrderLineRow).where(OrderLineRow.order_id == order_id)
                                .order_by(OrderLineRow.position)).scalars().all()
        cur = row.currency
        return OrderRecord(
            order_id=row.order_id, customer_id=row.customer_id, status=row.status, total_minor=row.total_minor,
            currency=cur, placed_at=row.placed_at, version=row.version, contact_email=row.contact_email,
            ship_to=dict(row.ship_to), shipping_method=row.shipping_method,
            lines=tuple({"lineId": x.line_id, "sku": x.sku, "productName": x.product_name, "quantity": x.quantity,
                         "unitPrice": {"amountMinor": x.unit_price_minor, "currency": cur},
                         "lineTotal": {"amountMinor": x.line_total_minor, "currency": cur}} for x in lines),
        )

    def set_status(self, order_id: str, status: str, version: int, now: datetime) -> None:
        self._s.execute(update(OrderRow).where(OrderRow.order_id == order_id)
                        .values(status=status, version=version, updated_at=now))


class SqlInvoiceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def next_number(self, year: int) -> int:
        # Gapless per year (guide §6.2): the counter row is locked until this transaction ends, and a
        # rollback gives the number back. Sequences would leave gaps.
        self._s.execute(text("INSERT INTO invoice_counter (year, last_seq) VALUES (:y, 0) ON CONFLICT (year) DO NOTHING"),
                        {"y": year})
        return int(self._s.execute(text(
            "UPDATE invoice_counter SET last_seq = last_seq + 1 WHERE year = :y RETURNING last_seq"), {"y": year}).scalar_one())

    def save(self, inv: StoredInvoice, total_minor: int, currency: str) -> None:
        self._s.add(InvoiceRow(invoice_id=inv.invoice_id, order_id=inv.order_id, number=inv.number,
                               total_minor=total_minor, currency=currency, document=_jsonable(inv.document),
                               issued_at=inv.issued_at))
        self._s.flush()

    def for_order(self, order_id: str) -> StoredInvoice | None:
        row = self._s.execute(select(InvoiceRow).where(InvoiceRow.order_id == order_id)).scalar_one_or_none()
        if row is None:
            return None
        doc = dict(row.document)
        if isinstance(doc.get("expiresAt"), str):
            doc["expiresAt"] = datetime.fromisoformat(doc["expiresAt"])
        elif isinstance(doc.get("expiresAt"), int):
            doc["expiresAt"] = from_millis(doc["expiresAt"])
        return StoredInvoice(row.invoice_id, row.order_id, row.number, doc, row.issued_at)
