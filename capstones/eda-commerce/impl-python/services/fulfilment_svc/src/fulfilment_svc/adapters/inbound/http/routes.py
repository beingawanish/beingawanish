"""Fake warehouse knobs: ``PUT /admin/fakes/wms`` (admin.yaml ``FakeWmsConfig``)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from edacommon.errors import DomainError
from edacommon.http import Authenticator, Principal, require_scope
from fastapi import APIRouter, Depends

from fulfilment_svc.adapters.outbound.wms.fake.wms import RATES, FakeWms


def fake_wms_router(wms: FakeWms, auth: Authenticator) -> APIRouter:
    router = APIRouter(tags=["fakes"])
    ops = Depends(require_scope(auth, "ops"))

    @router.put("/admin/fakes/wms")
    def set_config(body: dict[str, Any], principal: Principal = ops) -> dict[str, Any]:
        for k in RATES:
            if k in body and not 0 <= float(body[k]) <= 1:
                raise DomainError(f"{k} must be between 0 and 1", problem_type="validation-error", status=400)
        for k, v in body.items():
            if (k.endswith("Ms") or k == "manifestLines") and (not isinstance(v, int) or v < 0):
                raise DomainError(f"{k} must be a non-negative integer", problem_type="validation-error", status=400)
        wms.config = wms.config.merged(body)
        return asdict(wms.config)

    return router
