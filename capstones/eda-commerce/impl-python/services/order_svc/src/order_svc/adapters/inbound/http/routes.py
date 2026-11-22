"""Orders API (orders.yaml) and saga ops endpoints (admin.yaml)."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Annotated, Any

from edacommon.db import Database, UnitOfWork
from edacommon.errors import DomainError
from edacommon.http import Authenticator, Principal, require_scope
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from order_svc.adapters.outbound.persistence.queries import SqlReadModel, SqlWriteModel
from order_svc.adapters.outbound.persistence.repositories import SqlInvoiceRepository
from order_svc.application.ports import DocumentStore
from order_svc.application.queries import OrderQueries


class NotFound(DomainError):
    problem_type = "not-found"
    status = 404


class BadCursor(DomainError):
    problem_type = "validation-error"
    status = 400


def _enc(cur: tuple[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(cur).encode()).decode()


def _dec(s: str) -> tuple[str, str]:
    try:
        a, b = json.loads(base64.urlsafe_b64decode(s.encode()))
        return str(a), str(b)
    except Exception as exc:
        raise BadCursor("invalid cursor") from exc


def orders_router(db: Database, documents: DocumentStore, auth: Authenticator, read_schema: str = "order_history") -> APIRouter:
    router = APIRouter(tags=["orders"])
    shop = Depends(require_scope(auth, "shop"))

    def queries(uow: UnitOfWork) -> OrderQueries:
        return OrderQueries(SqlReadModel(uow.session, read_schema), SqlWriteModel(uow.session))

    def owned(body: dict[str, Any], p: Principal) -> bool:
        return body.get("customerId") == p.subject or p.has("ops")

    @router.get("/orders/{order_id}")
    def get_order(order_id: str, request: Request, principal: Principal = shop) -> Response:
        with db.unit_of_work() as uow:
            found = queries(uow).get(order_id)
        if found is None or not owned(found[0], principal):
            raise NotFound(f"no order {order_id}")
        body, in_flight = found
        body.pop("customerId", None)
        etag = f'"{body["version"]}"'
        headers = {"ETag": etag}
        if in_flight:
            headers["Retry-After"] = "1"
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(body, headers=headers)

    @router.get("/orders/{order_id}/invoice")
    def get_invoice(order_id: str, principal: Principal = shop) -> Response:
        with db.unit_of_work() as uow:
            found = queries(uow).get(order_id)
            inv = SqlInvoiceRepository(uow.session).for_order(order_id)
        if found is None or inv is None or not owned(found[0], principal):
            raise NotFound(f"no invoice for order {order_id}")
        # Claim check: never stream the PDF through the service (ADR-0009); 5-minute pre-signed URL.
        return RedirectResponse(documents.presign(inv.document, 300), status_code=302)

    @router.get("/customers/me/orders")
    def my_orders(
        principal: Principal = shop,
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        status: str | None = None,
    ) -> dict[str, Any]:
        after = _dec(cursor) if cursor else None
        statuses = [s for s in status.split(",") if s] if status else None
        with db.unit_of_work() as uow:
            rows = SqlReadModel(uow.session, read_schema).orders_of(
                principal.subject, limit=limit + 1, after=after, statuses=statuses
            )
        more = len(rows) > limit
        rows = rows[:limit]
        nxt = _enc(rows[-1]["_cursor"]) if more and rows else None
        for r in rows:
            r.pop("_cursor")
        return {"items": rows, "nextCursor": nxt}

    return router


def ops_caller(auth: Authenticator) -> Callable[[Request], str]:
    """Caller identity for /ops endpoints; requires the ``ops`` scope."""
    dep = require_scope(auth, "ops")

    def get(request: Request) -> str:
        return dep(request).subject

    return get
