"""HTTP adapters of payment-svc: ``POST /webhooks/psp`` (webhooks.yaml) and the fake PSP knobs
``GET|PUT /admin/fakes/psp`` (admin.yaml)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from edacommon.http import Authenticator, Principal, problem, require_scope
from edacommon.ids import Clock
from edacommon.webhooks import WebhookReceiver
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from payment_svc.adapters.outbound.psp.fake.psp import FakePsp


def webhook_router(receiver: WebhookReceiver, clock: Clock) -> APIRouter:
    router = APIRouter(tags=["webhooks"])

    @router.post("/webhooks/psp")
    async def receive(request: Request) -> Response:
        raw = await request.body()
        result = await run_in_threadpool(
            receiver.receive,
            raw_body=raw,
            timestamp=request.headers.get("X-Webhook-Timestamp"),
            signature=request.headers.get("X-Psp-Signature"),
            now=clock.now(),
        )
        if result.status == 401:
            return problem(401, "webhook-signature", "Unauthorized", result.detail)
        if result.status == 400:
            return problem(400, "validation-error", "Bad request", result.detail)
        return JSONResponse({"status": result.outcome.value}, status_code=200)

    return router


def fake_psp_router(psp: FakePsp, auth: Authenticator) -> APIRouter:
    router = APIRouter(tags=["fakes"])
    ops = Depends(require_scope(auth, "ops"))

    @router.get("/admin/fakes/psp")
    def get_config(principal: Principal = ops) -> dict[str, Any]:
        return asdict(psp.config)

    @router.put("/admin/fakes/psp")
    def set_config(body: dict[str, Any], principal: Principal = ops) -> dict[str, Any]:
        for k in ("declineRate", "timeoutRate", "duplicateWebhookRate"):
            if k in body and not 0 <= float(body[k]) <= 1:
                from edacommon.errors import DomainError

                raise DomainError(f"{k} must be between 0 and 1", problem_type="validation-error", status=400)
        psp.config = psp.config.merged(body)
        return asdict(psp.config)

    return router
