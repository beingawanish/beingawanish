from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.consumer import Outcome
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde
from edacommon.testing.service import Published, ServiceHarness
from fastapi.testclient import TestClient
from moto import mock_aws
from shipping_svc.adapters.inbound.http.routes import fake_carrier_router, webhook_router
from shipping_svc.adapters.inbound.messaging.handlers import build_registry
from shipping_svc.adapters.outbound.carrier.fake.carrier import FakeCarrier, FakeCarrierConfig
from shipping_svc.adapters.outbound.storage.labels import ClaimCheckLabels
from shipping_svc.config import Settings
from shipping_svc.main import wire

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
ORDER = "0193a1c4-0000-7000-8000-00000000e001"
ADDRESS = {
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
        self.settings = Settings()
        self.webhook_statuses: list[int] = []
        self.carrier = FakeCarrier(
            FakeCarrierConfig(duplicateRate=0, outOfOrderRate=0, exceptionRate=0, stepDelayMs=1000, bookingFailureRate=0),
            url=self.settings.carrier_webhook_url,
            secret=self.settings.carrier_webhook_secret,
            send=self._post,
            seed=11,
            wall_clock=h.clock.now,
        )
        infra = Infrastructure(settings=self.settings, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.cc = ClaimCheckStore(s3, h.metrics)
        self.w = wire(self.settings, infra, self.carrier, ClaimCheckLabels(self.cc))
        self.registry = build_registry(self.w.shipments_for, h.clock)
        app = create_app(
            self.settings,
            readiness=Readiness(),
            instrument=False,
            routers=[webhook_router(self.w.receiver, h.clock), fake_carrier_router(self.carrier, Authenticator(self.settings))],
        )
        self.http = TestClient(app)

    def _post(self, url: str, headers: dict[str, str], raw: bytes) -> None:
        self.webhook_statuses.append(self.http.post("/webhooks/carrier", content=raw, headers=headers).status_code)

    def packed(self, fid: str = "f-1", event_id: str | None = None) -> Outcome:
        cc = {
            "bucket": "packing-manifests",
            "objectKey": "k",
            "contentType": "application/json",
            "sizeBytes": 1,
            "sha256": "0" * 64,
        }
        body = {
            "orderId": ORDER,
            "fulfilmentId": fid,
            "warehouseId": "wh-berlin-1",
            "parcels": [{"parcelId": "p1", "weightGrams": 900, "lengthMm": 400, "widthMm": 300, "heightMm": 150}],
            "manifest": cc,
            "shipTo": ADDRESS,
            "shippingMethod": "STANDARD",
            "packedAt": self.h.clock.now(),
        }
        rec = self.h.command(R.OrderPacked, body, key=ORDER, producer="fulfilment-svc", event_id=event_id)
        return self.h.deliver(self.registry, rec)

    def settle(self, *, force: bool = True) -> list[Published]:
        """Deliver planned webhooks (all of them, or only those due/advanced), then process them."""
        for raw in self.carrier.due(force=force):
            self.carrier.deliver(raw)
        self.w.tracking.run_once()
        return self.out()

    def out(self) -> list[Published]:
        return [p for p in self.h.published() if p.topic == "shipping.events.v1"]


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="shipping-labels")
        h = ServiceHarness(
            url=pg_url,
            migrations=MIGRATIONS,
            group="shipping-svc",
            serde=AvroSerde(schema_registry),
            clock=clock,
            metrics=metrics_reader[0],
        )
        yield Svc(h, s3)
        h.close()
