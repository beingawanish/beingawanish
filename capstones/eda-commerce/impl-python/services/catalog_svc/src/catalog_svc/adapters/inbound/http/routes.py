"""Catalog API (catalog.yaml): browse and admin upsert."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from edacommon.db import Database, UnitOfWork
from edacommon.envelope import Causation, caused_by
from edacommon.errors import DomainError
from edacommon.http import Authenticator, CamelModel, Principal, require_scope
from edacommon.ids import Clock
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from catalog_svc.adapters.outbound.persistence.repositories import SqlCatalogRepository
from catalog_svc.application.catalog import Catalog
from catalog_svc.domain.product import Price, Product, ProductStatus, availability


class MoneyIn(CamelModel):
    amount_minor: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ProductWrite(CamelModel):
    name: str
    status: ProductStatus
    list_price: MoneyIn
    description: str | None = None
    brand: str | None = None
    category_path: list[str] = []
    attributes: dict[str, str] = {}
    weight_grams: int | None = None
    image_urls: list[str] = []
    sale_price: MoneyIn | None = None


class NotFound(DomainError):
    problem_type = "not-found"
    status = 404


def view(p: Product, available: int | None) -> dict[str, Any]:
    cur = p.price.currency
    return {
        "sku": p.sku,
        "name": p.name,
        "description": p.description,
        "brand": p.brand,
        "categoryPath": list(p.category_path),
        "attributes": dict(p.attributes),
        "status": p.status.value,
        "weightGrams": p.weight_grams,
        "imageUrls": list(p.image_urls),
        "listPrice": {"amountMinor": p.price.list_minor, "currency": cur},
        "salePrice": {"amountMinor": p.price.sale_minor, "currency": cur} if p.price.sale_minor is not None else None,
        "availability": availability(available),
        "version": p.version,
    }


def catalog_router(db: Database, catalog_for: Callable[[UnitOfWork], Catalog], clock: Clock, auth: Authenticator) -> APIRouter:
    router = APIRouter()
    ops = Depends(require_scope(auth, "ops"))

    @router.get("/products", tags=["browse"])
    def list_products(
        category: str | None = None,
        q: Annotated[str | None, Query(max_length=100)] = None,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 24,
    ) -> dict[str, Any]:
        with db.unit_of_work() as uow:
            rows = SqlCatalogRepository(uow.session).browse(category=category, q=q, after=cursor, limit=limit + 1)
        more = len(rows) > limit
        rows = rows[:limit]
        # Opaque enough for a capstone: the last SKU seen (guide §6.5 asks for opaque cursors).
        return {"items": [view(p, a) for p, a in rows], "nextCursor": rows[-1][0].sku if more and rows else None}

    @router.get("/products/{sku}", tags=["browse"])
    def get_product(sku: str, request: Request) -> Response:
        with db.unit_of_work() as uow:
            repo = SqlCatalogRepository(uow.session)
            p = repo.get(sku)
            av = repo.available(sku)
        if p is None:
            raise NotFound(f"no product {sku}")
        etag = f'"{p.version}"'
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(view(p, av), headers={"ETag": etag})

    @router.put("/admin/products/{sku}", tags=["catalog-admin"])
    def upsert(sku: str, body: ProductWrite, principal: Principal = ops) -> dict[str, Any]:
        if body.sale_price and body.sale_price.currency != body.list_price.currency:
            raise DomainError("salePrice currency must match listPrice", problem_type="validation-error", status=400)
        try:
            price = Price(
                body.list_price.amount_minor, body.list_price.currency, body.sale_price.amount_minor if body.sale_price else None
            )
        except ValueError as exc:
            raise DomainError(str(exc), problem_type="validation-error", status=400) from exc
        incoming = Product(
            sku=sku,
            name=body.name,
            status=body.status,
            price=price,
            description=body.description,
            brand=body.brand,
            category_path=tuple(body.category_path),
            attributes=dict(body.attributes),
            weight_grams=body.weight_grams,
            image_urls=tuple(body.image_urls),
        )
        with caused_by(Causation(correlation_id=sku)), db.unit_of_work() as uow:
            p = catalog_for(uow).upsert(incoming, clock.now())
            av = SqlCatalogRepository(uow.session).available(sku)
        return view(p, av)

    return router
