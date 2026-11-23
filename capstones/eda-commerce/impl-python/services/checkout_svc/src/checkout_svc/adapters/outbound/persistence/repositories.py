"""Postgres adapters of checkout-svc: carts, checkouts and the catalog read model (SQL Core; the
tables are defined in migration 0002)."""

from __future__ import annotations

from datetime import datetime

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import text
from sqlalchemy.orm import Session

from checkout_svc.application.ports import Cart
from checkout_svc.domain.pricing import CatalogEntry


class SqlCartRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, cart: Cart, now: datetime) -> None:
        self._s.execute(
            text(
                "INSERT INTO cart (cart_id, customer_id, status, currency, version, created_at, updated_at) "
                "VALUES (:i, :c, :s, :cur, :v, :n, :n)"
            ),
            {"i": cart.cart_id, "c": cart.customer_id, "s": cart.status, "cur": cart.currency, "v": cart.version, "n": now},
        )

    def get(self, cart_id: str, *, for_update: bool = False) -> Cart | None:
        r = (
            self._s.execute(text("SELECT * FROM cart WHERE cart_id = :i" + (" FOR UPDATE" if for_update else "")), {"i": cart_id})
            .mappings()
            .first()
        )
        if r is None:
            return None
        items = self._s.execute(
            text("SELECT sku, quantity FROM cart_line WHERE cart_id = :i ORDER BY position"), {"i": cart_id}
        ).all()
        return Cart(
            r["cart_id"], r["customer_id"], r["status"], r["currency"], int(r["version"]), tuple((s, int(q)) for s, q in items)
        )

    def save(self, cart: Cart, now: datetime) -> None:
        self._s.execute(
            text("UPDATE cart SET status = :s, version = :v, updated_at = :n WHERE cart_id = :i"),
            {"s": cart.status, "v": cart.version, "n": now, "i": cart.cart_id},
        )
        self._s.execute(text("DELETE FROM cart_line WHERE cart_id = :i"), {"i": cart.cart_id})
        for pos, (sku, qty) in enumerate(cart.items):
            self._s.execute(
                text("INSERT INTO cart_line (cart_id, sku, quantity, position) VALUES (:i, :s, :q, :p)"),
                {"i": cart.cart_id, "s": sku, "q": qty, "p": pos},
            )

    def record_checkout(self, *, checkout_id: str, order_id: str, cart: Cart, total_minor: int, now: datetime) -> None:
        self._s.execute(
            text(
                "INSERT INTO checkout (checkout_id, order_id, cart_id, customer_id, total_minor, currency, order_status, "
                "created_at) "
                "VALUES (:ck, :o, :c, :cu, :t, :cur, 'SUBMITTED', :n)"
            ),
            {
                "ck": checkout_id,
                "o": order_id,
                "c": cart.cart_id,
                "cu": cart.customer_id,
                "t": total_minor,
                "cur": cart.currency,
                "n": now,
            },
        )

    def set_order_status(self, order_id: str, status: str) -> None:
        self._s.execute(text("UPDATE checkout SET order_status = :s WHERE order_id = :o"), {"s": status, "o": order_id})


class SqlCatalogView:
    """``catalog_view``: one row per SKU merged from three compacted topics; each part keeps the
    version of the snapshot it came from and only a strictly newer snapshot replaces it."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def entries(self, skus: list[str]) -> dict[str, CatalogEntry]:
        if not skus:
            return {}
        rows = self._s.execute(text("SELECT * FROM catalog_view WHERE sku = ANY(:s)"), {"s": skus}).mappings().all()
        return {
            r["sku"]: CatalogEntry(
                r["sku"],
                r["name"],
                r["status"],
                r["list_minor"],
                r["sale_minor"],
                r["currency"],
                r["available"],
                r["priced_as_of"],
            )
            for r in rows
        }

    def _apply(self, sku: str, cols: dict[str, object], version_col: str, version: int) -> bool:
        names = list(cols)
        sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in [*names, version_col]) + ", updated_at = now()"
        res = self._s.execute(
            text(
                f"INSERT INTO catalog_view (sku, {', '.join(names)}, {version_col}) "
                f"VALUES (:sku, {', '.join(':' + c for c in names)}, :ver) "
                f"ON CONFLICT (sku) DO UPDATE SET {sets} "
                f"WHERE catalog_view.{version_col} IS NULL OR catalog_view.{version_col} < EXCLUDED.{version_col}"
            ),
            {"sku": sku, "ver": version, **cols},
        )
        return bool(res.rowcount)  # type: ignore[attr-defined]

    def apply_product(self, sku: str, name: str, status: str, version: int, at: datetime) -> bool:
        return self._apply(sku, {"name": name, "status": status}, "product_version", version)

    def apply_price(self, sku: str, list_minor: int, sale_minor: int | None, currency: str, version: int, at: datetime) -> bool:
        return self._apply(
            sku,
            {"list_minor": list_minor, "sale_minor": sale_minor, "currency": currency, "priced_as_of": at},
            "price_version",
            version,
        )

    def apply_stock(self, sku: str, available: int, version: int, at: datetime) -> bool:
        return self._apply(sku, {"available": available}, "stock_version", version)


class OutboxPublisher:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
