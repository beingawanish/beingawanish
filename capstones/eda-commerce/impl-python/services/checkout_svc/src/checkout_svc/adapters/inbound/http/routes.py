"""Checkout API (checkout.yaml): carts with ETags, and POST /checkouts with Idempotency-Key."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Literal

from edacommon.db import Database, UnitOfWork
from edacommon.errors import DomainError
from edacommon.http import Authenticator, CamelModel, Principal, require_scope
from edacommon.idempotency import HEADER, IdempotencyStore, StoredResponse
from edacommon.ids import Clock
from edacommon.saga.ops import to_response
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import EmailStr, Field
from starlette.concurrency import run_in_threadpool

from checkout_svc.application.checkout import Checkout
from checkout_svc.domain.money import Money
from checkout_svc.domain.pricing import CheckoutRefused

_STATUS = {"not-found": 404, "precondition-failed": 412, "validation-error": 400}


def refused(exc: CheckoutRefused) -> DomainError:
    return DomainError(exc.detail, problem_type=exc.problem_type, status=_STATUS.get(exc.problem_type, 422))


class MoneyIn(CamelModel):
    amount_minor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class AddressIn(CamelModel):
    recipient_name: str = Field(max_length=200)
    line1: str = Field(max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(max_length=100)
    region: str | None = Field(default=None, max_length=100)
    postal_code: str = Field(max_length=20)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    phone: str | None = Field(default=None, max_length=30)


class CheckoutRequest(CamelModel):
    cart_id: str
    shipping_address: AddressIn
    contact_email: EmailStr
    shipping_method: Literal["STANDARD", "EXPRESS"]
    payment_method_token: str
    expected_total: MoneyIn


class SetQuantity(CamelModel):
    quantity: int = Field(ge=1, le=99)


def checkout_router(
    db: Database, checkout_for: Callable[[UnitOfWork], Checkout], clock: Clock, auth: Authenticator, idempotency: IdempotencyStore
) -> APIRouter:
    router = APIRouter()
    shop = Depends(require_scope(auth, "shop"))

    def etagged(body: dict[str, Any], version: int, status: int = 200, extra: dict[str, str] | None = None) -> JSONResponse:
        return JSONResponse(body, status_code=status, headers={"ETag": f'"{version}"', **(extra or {})})

    @router.post("/carts", tags=["carts"], status_code=201)
    async def create_cart(request: Request, principal: Principal = shop) -> Response:
        raw = await request.body()
        currency = (json.loads(raw) if raw else {}).get("currency", "EUR")

        def action(uow: UnitOfWork) -> StoredResponse:
            co = checkout_for(uow)
            cart = co.create_cart(principal.subject, currency, clock.now())
            return StoredResponse(
                201,
                json.dumps(co.view(cart, clock.now())).encode(),
                {"content-type": "application/json", "Location": f"/carts/{cart.cart_id}", "ETag": f'"{cart.version}"'},
            )

        return to_response(
            await run_in_threadpool(
                idempotency.execute,
                db,
                caller=principal.subject,
                key=request.headers.get(HEADER),
                method="POST",
                path=request.url.path,
                body=raw,
                action=action,
            )
        )

    @router.get("/carts/{cart_id}", tags=["carts"])
    def get_cart(cart_id: str, principal: Principal = shop) -> JSONResponse:
        try:
            with db.unit_of_work() as uow:
                co = checkout_for(uow)
                cart = co.get_cart(cart_id, principal.subject)
                return etagged(co.view(cart, clock.now()), cart.version)
        except CheckoutRefused as exc:
            raise refused(exc) from exc

    @router.put("/carts/{cart_id}/items/{sku}", tags=["carts"])
    def set_item(cart_id: str, sku: str, body: SetQuantity, request: Request, principal: Principal = shop) -> JSONResponse:
        im = request.headers.get("If-Match")
        try:
            if_match = int(im.strip('"W/')) if im else None
        except ValueError:
            raise DomainError("If-Match must be an ETag from this API", problem_type="validation-error", status=400) from None
        try:
            with db.unit_of_work() as uow:
                co = checkout_for(uow)
                cart = co.set_item(cart_id, principal.subject, sku, body.quantity, if_match, clock.now())
                return etagged(co.view(cart, clock.now()), cart.version)
        except CheckoutRefused as exc:
            raise refused(exc) from exc

    @router.delete("/carts/{cart_id}/items/{sku}", tags=["carts"])
    def remove_item(cart_id: str, sku: str, principal: Principal = shop) -> JSONResponse:
        try:
            with db.unit_of_work() as uow:
                co = checkout_for(uow)
                cart = co.remove_item(cart_id, principal.subject, sku, clock.now())
                return etagged(co.view(cart, clock.now()), cart.version)
        except CheckoutRefused as exc:
            raise refused(exc) from exc

    @router.post("/checkouts", tags=["checkouts"], status_code=202)
    async def submit(body: CheckoutRequest, request: Request, principal: Principal = shop) -> Response:
        raw = await request.body()

        def action(uow: UnitOfWork) -> StoredResponse:
            try:
                accepted = checkout_for(uow).submit(
                    customer_id=principal.subject,
                    cart_id=body.cart_id,
                    shipping_address=body.shipping_address.model_dump(by_alias=True),
                    contact_email=str(body.contact_email),
                    shipping_method=body.shipping_method,
                    payment_token=body.payment_method_token,
                    expected_total=Money(body.expected_total.amount_minor, body.expected_total.currency),
                    now=clock.now(),
                )
            except CheckoutRefused as exc:
                raise refused(exc) from exc
            return StoredResponse(
                202,
                json.dumps(accepted).encode(),
                {"content-type": "application/json", "Location": accepted["statusUrl"], "Retry-After": "1"},
            )

        return to_response(
            await run_in_threadpool(
                idempotency.execute,
                db,
                caller=principal.subject,
                key=request.headers.get(HEADER),
                method="POST",
                path=request.url.path,
                body=raw,
                action=action,
            )
        )

    return router
