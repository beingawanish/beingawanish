from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from edacommon.db import UnitOfWork
from edacommon.testing.service import ServiceHarness
from inventory_svc.adapters.inbound.messaging.handlers import build_registry
from inventory_svc.adapters.outbound.persistence.repositories import OutboxPublisher, SqlInventoryRepository
from inventory_svc.application.use_cases import Inventory
from inventory_svc.config import Settings

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


class Svc:
    def __init__(self, h: ServiceHarness, settings: Settings) -> None:
        self.h = h
        self.settings = settings

        def make(uow: UnitOfWork) -> Inventory:
            return Inventory(repo=SqlInventoryRepository(uow.session), events=OutboxPublisher(uow.session, h.outbox),
                             max_ttl=settings.reservation_ttl)

        self.inventory_for: Callable[[UnitOfWork], Inventory] = make
        self.registry = build_registry(make, h.clock)

    def set_stock(self, sku: str, on_hand: int) -> None:
        with self.h.db.unit_of_work() as uow:
            self.inventory_for(uow).set_stock(sku, on_hand, self.h.clock.now())

    def level(self, sku: str) -> Any:
        with self.h.db.unit_of_work() as uow:
            return SqlInventoryRepository(uow.session).stock(sku)


@pytest.fixture
def svc(pg_url: str, serde: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    h = ServiceHarness(url=pg_url, migrations=MIGRATIONS, group="inventory-svc", serde=serde, clock=clock,
                       metrics=metrics_reader[0])
    yield Svc(h, Settings())
    h.close()


@pytest.fixture
def serde(schema_registry: Any) -> Any:
    from edacommon.serde import AvroSerde

    return AvroSerde(schema_registry)
