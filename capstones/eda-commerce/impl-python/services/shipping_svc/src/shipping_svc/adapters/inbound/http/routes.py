"""HTTP adapters of shipping-svc: ``POST /webhooks/carrier`` (webhooks.yaml) and the fake carrier
knobs ``PUT /admin/fakes/carrier`` and ``POST /admin/fakes/carrier/shipments/{trackingNumber}/advance``
(admin.yaml)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from edacommon.errors import DomainError
from edacommon.http import Authenticator, Principal, problem, require_scope
from edacommon.ids import Clock
from edacommon.webhooks import WebhookReceiver
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from shipping_svc.adapters.outbound.carrier.fake.carrier import RATES, FakeCarrier

ADVANCE_TO = {"PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY", "DELIVERED", "EXCEPTION"}


class NotFound(DomainError):
    problem_type = "not-found"
    status = 404


def webhook_router(receiver: WebhookReceiver, clock: Clock) -> APIRouter:
    router = APIRouter(tags=["webhooks"])

    @router.post("/webhooks/carrier")
    async def receive(request: Request) -> Response:
        raw = await request.body()
        result = await run_in_threadpool(
            receiver.receive,
            raw_body=raw,
            timestamp=request.headers.get("X-Webhook-Timestamp"),
            signature=request.headers.get("X-Carrier-Signature"),
            now=clock.now(),
        )
        if result.status == 401:
            return problem(401, "webhook-signature", "Unauthorized", result.detail)
        if result.status == 400:
            return problem(400, "validation-error", "Bad request", result.detail)
        return JSONResponse({"status": result.outcome.value}, status_code=200)

    return router


def fake_carrier_router(carrier: FakeCarrier, auth: Authenticator) -> APIRouter:
    router = APIRouter(tags=["fakes"])
    ops = Depends(require_scope(auth, "ops"))

    @router.put("/admin/fakes/carrier")
    def set_config(body: dict[str, Any], principal: Principal = ops) -> dict[str, Any]:
        for k in RATES:
            if k in body and not 0 <= float(body[k]) <= 1:
                raise DomainError(f"{k} must be between 0 and 1", problem_type="validation-error", status=400)
        if "stepDelayMs" in body and not isinstance(body["stepDelayMs"], int):
            raise DomainError("stepDelayMs must be an integer", problem_type="validation-error", status=400)
        carrier.config = carrier.config.merged(body)
        return asdict(carrier.config)

    @router.post("/admin/fakes/carrier/shipments/{tracking_number}/advance", status_code=202)
    def advance(tracking_number: str, request_body: dict[str, Any] | None = None, principal: Principal = ops) -> dict[str, str]:
        body = request_body or {}
        to = body.get("toStatus")
        if to is not None and to not in ADVANCE_TO:
            raise DomainError(f"toStatus must be one of {sorted(ADVANCE_TO)}", problem_type="validation-error", status=400)
        # exceptionCode is an extension of this build (admin.yaml defines toStatus only).
        if not carrier.advance(tracking_number, to, body.get("exceptionCode")):
            raise NotFound(f"no shipment with tracking number {tracking_number}")
        return {"trackingNumber": tracking_number, "status": "SCHEDULED"}

    return router
