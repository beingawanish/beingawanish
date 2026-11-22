"""Returns API (returns.yaml) and the ops decision endpoint; saga ops come from edacommon."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from edacommon.db import Database, UnitOfWork
from edacommon.errors import DomainError
from edacommon.http import Authenticator, CamelModel, Principal, require_scope
from edacommon.idempotency import HEADER, IdempotencyStore, StoredResponse
from edacommon.ids import Clock, rfc3339
from edacommon.saga.ops import to_response
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from returns_svc.application.ports import LabelLinks, ReturnRecord
from returns_svc.application.returns import ReturnNotFound, ReturnsSaga


class RequestLine(CamelModel):
    line_id: str
    quantity: Annotated[int, Field(ge=1)]


class ReturnRequestBody(CamelModel):
    order_id: str
    lines: Annotated[list[RequestLine], Field(min_length=1)]
    reason: Literal["DAMAGED", "WRONG_ITEM", "NOT_AS_DESCRIBED", "CHANGED_MIND", "OTHER"]
    comment: Annotated[str | None, Field(max_length=1000)] = None


class DecisionBody(CamelModel):
    decision: Literal["APPROVE", "REJECT", "RETRY_REFUND", "CLOSE_WITHOUT_REFUND"]
    note: Annotated[str | None, Field(max_length=1000)] = None


class NoLabel(DomainError):
    problem_type = "label-not-available"
    status = 404


def return_json(r: ReturnRecord) -> dict[str, Any]:
    def outcome(x: Any) -> str | None:
        outs = {i["outcome"] for i in x.inspection}
        if not outs:
            return None
        if len(outs) == 1:
            o = next(iter(outs))
            return o if o in ("RESTOCKABLE", "DAMAGED", "MISSING") else None
        # Mixed outcomes on one line: report the worst (the timeline holds the detail).
        return "MISSING" if "MISSING" in outs else "DAMAGED"

    return {
        "returnId": r.return_id,
        "orderId": r.order_id,
        "rmaNumber": r.rma_number,
        "status": r.status,
        "lines": [{"lineId": x.line_id, "sku": x.sku, "quantity": x.quantity, "inspectionOutcome": outcome(x)} for x in r.lines],
        "refundAmount": {"amountMinor": r.refund_minor, "currency": r.currency} if r.refund_minor is not None else None,
        "labelAvailable": r.label is not None,
        "parcelDueBy": rfc3339(r.parcel_due_by) if r.parcel_due_by else None,
        "requestedAt": rfc3339(r.requested_at),
    }


def returns_router(
    db: Database,
    saga_for: Callable[[UnitOfWork], ReturnsSaga],
    links: LabelLinks,
    clock: Clock,
    auth: Authenticator,
    idempotency: IdempotencyStore,
) -> APIRouter:
    router = APIRouter(tags=["returns"])
    shop = Depends(require_scope(auth, "shop"))
    ops = Depends(require_scope(auth, "ops"))

    def owned(r: ReturnRecord | None, p: Principal, return_id: str) -> ReturnRecord:
        if r is None or (r.customer_id != p.subject and not p.has("ops")):
            raise ReturnNotFound(f"no return {return_id}")
        return r

    @router.post("/returns", status_code=202)
    async def request_return(body: ReturnRequestBody, request: Request, principal: Principal = shop) -> Response:
        raw = await request.body()

        def action(uow: UnitOfWork) -> StoredResponse:
            rec = saga_for(uow).request(
                uow,
                caller=principal.subject,
                is_ops=principal.has("ops"),
                order_id=body.order_id,
                lines=[(x.line_id, x.quantity) for x in body.lines],
                reason=body.reason,
                comment=body.comment,
                now=clock.now(),
            )
            return StoredResponse(
                202,
                json.dumps(return_json(rec)).encode(),
                {"content-type": "application/json", "Location": f"/returns/{rec.return_id}"},
            )

        stored = await run_in_threadpool(
            idempotency.execute,
            db,
            caller=principal.subject,
            key=request.headers.get(HEADER),
            method="POST",
            path=request.url.path,
            body=raw,
            action=action,
        )
        return to_response(stored)

    @router.get("/returns/{return_id}")
    def get_return(return_id: str, principal: Principal = shop) -> dict[str, Any]:
        with db.unit_of_work() as uow:
            r = owned(saga_for(uow).repo_for(uow).get(return_id), principal, return_id)
        return return_json(r)

    @router.get("/returns/{return_id}/label")
    def get_label(return_id: str, principal: Principal = shop) -> Response:
        with db.unit_of_work() as uow:
            r = owned(saga_for(uow).repo_for(uow).get(return_id), principal, return_id)
        if r.label is None:
            raise NoLabel(f"return {return_id} has no label yet")
        # Claim check: a 5-minute pre-signed URL, never the PDF through the service (ADR-0009).
        return RedirectResponse(links.presign(r.label, 300), status_code=302)

    @router.get("/orders/{order_id}/returns")
    def order_returns(order_id: str, principal: Principal = shop) -> dict[str, Any]:
        with db.unit_of_work() as uow:
            saga = saga_for(uow)
            found = saga.view_of_order(uow, order_id)
        if found is None or (found[0].customer_id != principal.subject and not principal.has("ops")):
            raise ReturnNotFound(f"no order {order_id}")
        view, left, returns = found
        ends = view.window_ends_at(saga.window)
        return {
            "returns": [return_json(r) for r in returns],
            "returnable": [
                {"lineId": x.line_id, "sku": x.sku, "quantity": left[x.line_id]} for x in view.lines if left[x.line_id] > 0
            ],
            "windowEndsAt": rfc3339(ends) if ends else None,
        }

    @router.post("/ops/returns/{return_id}/decision", status_code=202, tags=["returns-ops"])
    async def decide(return_id: str, body: DecisionBody, request: Request, principal: Principal = ops) -> Response:
        raw = await request.body()

        def action(uow: UnitOfWork) -> StoredResponse:
            rec = saga_for(uow).decide(uow, return_id=return_id, decision=body.decision, note=body.note)
            return StoredResponse(202, json.dumps(return_json(rec)).encode(), {"content-type": "application/json"})

        stored = await run_in_threadpool(
            idempotency.execute,
            db,
            caller=principal.subject,
            key=request.headers.get(HEADER),
            method="POST",
            path=request.url.path,
            body=raw,
            action=action,
        )
        return to_response(stored)

    return router


def ops_caller(auth: Authenticator) -> Callable[[Request], str]:
    dep = require_scope(auth, "ops")

    def get(request: Request) -> str:
        return dep(request).subject

    return get


__all__ = ["JSONResponse", "ops_caller", "return_json", "returns_router"]
