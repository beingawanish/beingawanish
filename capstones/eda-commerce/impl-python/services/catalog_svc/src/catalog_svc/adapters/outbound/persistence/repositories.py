"""Postgres implementation of CatalogRepository, plus browse queries."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from catalog_svc.adapters.outbound.persistence.models import PriceRow, ProductRow, StockLevelViewRow
from catalog_svc.domain.product import Price, Product, ProductStatus, StockSnapshot


def _upsert(session: Session, model: Any, values: dict[str, Any], key: str) -> None:
    stmt = pg_insert(model).values(**values)
    session.execute(stmt.on_conflict_do_update(index_elements=[key], set_={k: stmt.excluded[k] for k in values if k != key}))


class SqlCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, sku: str, *, for_update: bool = False) -> Product | None:
        q = select(ProductRow, PriceRow).join(PriceRow, PriceRow.sku == ProductRow.sku).where(ProductRow.sku == sku)
        if for_update:
            q = q.with_for_update()
        r = self._s.execute(q).first()
        return self._product(r[0], r[1]) if r else None

    @staticmethod
    def _product(p: ProductRow, pr: PriceRow) -> Product:
        return Product(
            sku=p.sku,
            name=p.name,
            status=ProductStatus(p.status),
            description=p.description,
            brand=p.brand,
            category_path=tuple(p.category_path),
            attributes=dict(p.attributes),
            weight_grams=p.weight_grams,
            image_urls=tuple(p.image_urls),
            version=p.version,
            price=Price(pr.list_minor, pr.currency, pr.sale_minor, pr.price_list_id),
        )

    def save(self, p: Product, now: datetime) -> None:
        _upsert(
            self._s,
            ProductRow,
            {
                "sku": p.sku,
                "name": p.name,
                "description": p.description,
                "brand": p.brand,
                "category_path": list(p.category_path),
                "attributes": dict(p.attributes),
                "status": p.status.value,
                "weight_grams": p.weight_grams,
                "image_urls": list(p.image_urls),
                "version": p.version,
                "updated_at": now,
            },
            "sku",
        )
        _upsert(
            self._s,
            PriceRow,
            {
                "sku": p.sku,
                "price_list_id": p.price.price_list_id,
                "list_minor": p.price.list_minor,
                "sale_minor": p.price.sale_minor,
                "currency": p.price.currency,
                "updated_at": now,
            },
            "sku",
        )

    def stock_version(self, sku: str) -> int | None:
        return self._s.execute(select(StockLevelViewRow.version).where(StockLevelViewRow.sku == sku)).scalar_one_or_none()

    def save_stock(self, s: StockSnapshot) -> None:
        _upsert(
            self._s, StockLevelViewRow, {"sku": s.sku, "available": s.available, "version": s.version, "as_of": s.as_of}, "sku"
        )

    def available(self, sku: str) -> int | None:
        return self._s.execute(select(StockLevelViewRow.available).where(StockLevelViewRow.sku == sku)).scalar_one_or_none()

    def browse(self, *, category: str | None, q: str | None, after: str | None, limit: int) -> list[tuple[Product, int | None]]:
        stmt = (
            select(ProductRow, PriceRow, StockLevelViewRow.available)
            .join(PriceRow, PriceRow.sku == ProductRow.sku)
            .outerjoin(StockLevelViewRow, StockLevelViewRow.sku == ProductRow.sku)
            .where(ProductRow.status == ProductStatus.ACTIVE.value)
            .order_by(ProductRow.sku)
            .limit(limit)
        )
        if after:
            stmt = stmt.where(ProductRow.sku > after)
        if category:
            stmt = stmt.where(ProductRow.category_path.contains([category]))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(ProductRow.name.ilike(like), ProductRow.brand.ilike(like)))
        return [(self._product(p, pr), av) for p, pr, av in self._s.execute(stmt).all()]


class OutboxPublisher:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
