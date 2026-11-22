from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.consumer import Outcome
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde
from edacommon.testing.service import Published, ServiceHarness
from fulfilment_svc.adapters.inbound.jobs.warehouse import WarehouseEventPump
from fulfilment_svc.adapters.inbound.messaging.handlers import build_registry
from fulfilment_svc.adapters.outbound.storage.manifests import ClaimCheckManifests
from fulfilment_svc.adapters.outbound.wms.fake.wms import FakeWms, FakeWmsConfig
from fulfilment_svc.config import Settings
from fulfilment_svc.main import fulfilments_factory
from moto import mock_aws

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
ORDER = "0193a1c4-0000-7000-8000-00000000d001"
SHIP_TO = {
    "recipientName": "Jane Doe",
    "line1": "Invalidenstrasse 1",
    "line2": None,
    "city": "Berlin",
    "region": None,
    "postalCode": "10115",
    "countryCode": "DE",
    "phone": None,
}


class Svc:
    def __init__(self, h: ServiceHarness, s3: Any) -> None:
        self.h = h
        self.s3 = s3
        self.settings = Settings()
        self.wms = FakeWms(
            FakeWmsConfig(dropRequestRate=0, failRate=0, acceptDelayMs=1000, pickDelayMs=1000, packDelayMs=1000), seed=3
        )
        infra = Infrastructure(settings=self.settings, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.cc = ClaimCheckStore(s3, h.metrics)
        self.fulfilments_for = fulfilments_factory(infra, self.wms, ClaimCheckManifests(self.cc))
        self.registry = build_registry(self.fulfilments_for, h.clock)
        self.pump = WarehouseEventPump(h.db, self.wms, self.fulfilments_for, h.clock)

    def send(self, cls: type, body: dict[str, Any], *, producer: str = "order-svc", event_id: str | None = None) -> Any:
        rec = self.h.command(cls, body, key=ORDER, producer=producer, event_id=event_id)
        return rec, self.h.deliver(self.registry, rec)

    def request(self, fid: str = "f-1", attempt: int = 1) -> Any:
        rec, outcome = self.send(
            R.RequestFulfilment,
            {
                "orderId": ORDER,
                "fulfilmentId": fid,
                "lines": [
                    {
                        "lineId": "l-1",
                        "sku": "SKU-1001",
                        "productName": "Trail Running Shoe",
                        "quantity": 2,
                        "unitPrice": {"amountMinor": 12999, "currency": "EUR"},
                        "lineTotal": {"amountMinor": 25998, "currency": "EUR"},
                    }
                ],
                "shipTo": SHIP_TO,
                "shippingMethod": "STANDARD",
                "attempt": attempt,
            },
        )
        assert outcome is Outcome.SUCCESS
        return rec

    def advance(self, seconds: float) -> int:
        self.h.clock.advance(timedelta(seconds=seconds))
        return self.pump.run_once()

    def out(self) -> list[Published]:
        return [p for p in self.h.published() if p.topic == "fulfilment.events.v1"]


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="packing-manifests")
        h = ServiceHarness(
            url=pg_url,
            migrations=MIGRATIONS,
            group="fulfilment-svc",
            serde=AvroSerde(schema_registry),
            clock=clock,
            metrics=metrics_reader[0],
        )
        yield Svc(h, s3)
        h.close()
