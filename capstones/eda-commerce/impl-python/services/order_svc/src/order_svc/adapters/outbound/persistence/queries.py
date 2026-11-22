"""SQL reads for the Orders API: the order_history read model and the write-model fallback."""

from __future__ import annotations

from typing import Any

from edacommon.ids import rfc3339
from sqlalchemy import text
from sqlalchemy.orm import Session


def _money(minor: int, cur: str) -> dict[str, Any]:
    return {"amountMinor": int(minor), "currency": cur}


class SqlReadModel:
    def __init__(self, session: Session, schema: str = "order_history") -> None:
        self._s = session
        self._t = schema

    def order(self, order_id: str) -> dict[str, Any] | None:
        r = (
            self._s.execute(text(f"SELECT * FROM {self._t}.order_summary WHERE order_id = :o"), {"o": order_id})
            .mappings()
            .first()
        )
        if r is None:
            return None
        lines = (
            self._s.execute(text(f"SELECT * FROM {self._t}.order_line WHERE order_id = :o ORDER BY position"), {"o": order_id})
            .mappings()
            .all()
        )
        tl = (
            self._s.execute(text(f"SELECT * FROM {self._t}.timeline WHERE order_id = :o ORDER BY at, event_id"), {"o": order_id})
            .mappings()
            .all()
        )
        cur = r["currency"]
        body = self._summary(r)
        body.update(
            {
                "customerId": r["customer_id"],
                "lines": [
                    {
                        "lineId": x["line_id"],
                        "sku": x["sku"],
                        "productName": x["product_name"],
                        "quantity": x["quantity"],
                        "unitPrice": _money(x["unit_price_minor"], cur),
                        "lineTotal": _money(x["line_total_minor"], cur),
                        "returnedQuantity": x["returned_quantity"],
                    }
                    for x in lines
                ],
                "cancellationReason": r["cancellation_reason"],
                "shipment": (
                    {"carrier": r["carrier"], "trackingNumber": r["tracking_number"], "status": r["shipment_status"] or "UNKNOWN"}
                    if r["carrier"]
                    else None
                ),
                "invoiceAvailable": bool(r["invoice_available"]),
                "refundedTotal": _money(r["refunded_minor"], cur),
                "timeline": [
                    {
                        "at": rfc3339(x["at"]),
                        "kind": x["kind"],
                        "eventId": x["event_id"],
                        **({"description": x["description"]} if x["description"] else {}),
                    }
                    for x in tl
                ],
            }
        )
        return body

    @staticmethod
    def _summary(r: Any) -> dict[str, Any]:
        return {
            "orderId": r["order_id"],
            "status": r["status"],
            "total": _money(r["total_minor"], r["currency"]),
            "itemCount": r["item_count"],
            "placedAt": rfc3339(r["placed_at"]),
            "version": int(r["version"]),
        }

    def orders_of(
        self, customer_id: str, *, limit: int, after: tuple[str, str] | None, statuses: list[str] | None
    ) -> list[dict[str, Any]]:
        where = ["customer_id = :c"]
        params: dict[str, Any] = {"c": customer_id, "n": limit}
        if after:
            where.append("(placed_at, order_id) < (CAST(:pa AS timestamptz), :po)")
            params.update(pa=after[0], po=after[1])
        if statuses:
            where.append("status = ANY(:st)")
            params["st"] = statuses
        rows = (
            self._s.execute(
                text(
                    f"SELECT * FROM {self._t}.order_summary WHERE {' AND '.join(where)} "
                    "ORDER BY placed_at DESC, order_id DESC LIMIT :n"
                ),
                params,
            )
            .mappings()
            .all()
        )
        out = []
        for r in rows:
            s = self._summary(r)
            s["_cursor"] = (r["placed_at"].isoformat(), r["order_id"])
            out.append(s)
        return out


class SqlWriteModel:
    def __init__(self, session: Session) -> None:
        self._s = session

    def order_with_saga(self, order_id: str) -> tuple[dict[str, Any], str, int] | None:
        r = (
            self._s.execute(
                text(
                    "SELECT o.*, s.state, s.version AS saga_version FROM orders o JOIN saga_instance s ON s.saga_id = o.order_id "
                    "WHERE o.order_id = :o"
                ),
                {"o": order_id},
            )
            .mappings()
            .first()
        )
        if r is None:
            return None
        cur = r["currency"]
        lines = (
            self._s.execute(text("SELECT * FROM order_line WHERE order_id = :o ORDER BY position"), {"o": order_id})
            .mappings()
            .all()
        )
        body = {
            "orderId": r["order_id"],
            "customerId": r["customer_id"],
            "total": _money(r["total_minor"], cur),
            "itemCount": sum(x["quantity"] for x in lines),
            "placedAt": rfc3339(r["placed_at"]),
            "lines": [
                {
                    "lineId": x["line_id"],
                    "sku": x["sku"],
                    "productName": x["product_name"],
                    "quantity": x["quantity"],
                    "unitPrice": _money(x["unit_price_minor"], cur),
                    "lineTotal": _money(x["line_total_minor"], cur),
                    "returnedQuantity": 0,
                }
                for x in lines
            ],
            "invoiceAvailable": False,
            "refundedTotal": _money(0, cur),
            "shipment": None,
            "cancellationReason": None,
        }
        return body, str(r["state"]), int(r["saga_version"])
