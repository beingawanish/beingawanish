"""Admin API of inventory-svc: ``PUT /admin/stock/{sku}`` (admin.yaml, used by infra/scripts/seed.sh)."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from pydantic import Field

from edacommon.db import Database, UnitOfWork
from edacommon.envelope import Causation, caused_by
from edacommon.http import Authenticator, CamelModel, Principal, require_scope
from edacommon.ids import Clock
from inventory_svc.application.use_cases import Inventory


class SetStock(CamelModel):
    on_hand: int = Field(ge=0)


def admin_router(db: Database, inventory_for: Callable[[UnitOfWork], Inventory], clock: Clock,
                 auth: Authenticator) -> APIRouter:
    router = APIRouter(tags=["seed"])
    ops = Depends(require_scope(auth, "ops"))

    @router.put("/admin/stock/{sku}")
    def set_stock(sku: str, body: SetStock, principal: Principal = ops) -> dict[str, object]:
        with caused_by(Causation(correlation_id=sku)), db.unit_of_work() as uow:
            inv = inventory_for(uow)
            inv.set_stock(sku, body.on_hand, clock.now())
            (level,) = inv.repo.levels([sku])
        return {"sku": sku, "onHand": level.on_hand, "reserved": level.reserved, "available": level.available}

    return router
