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
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.idempotency import IdempotencyStore
from edacommon.runtime import Infrastructure
from edacommon.saga.ops import saga_ops_router
from edacommon.serde import AvroSerde
from edacommon.testing.service import Published, ServiceHarness
from fastapi.testclient import TestClient
from moto import mock_aws
from returns_svc.adapters.inbound.http.routes import ops_caller, returns_router
from returns_svc.adapters.inbound.jobs.deadlines import returns_deadline_sweeper
from returns_svc.adapters.inbound.messaging.handlers import build_registry
from returns_svc.adapters.outbound.storage.labels import ClaimCheckLabelLinks
from returns_svc.config import Settings
from returns_svc.main import saga_factory

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
ORDER = "0193a1c4-0000-7000-8000-00000000a901"
CUSTOMER = "cust-1"
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
        self.s3 = s3
        self.settings = Settings()
        infra = Infrastructure(settings=self.settings, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.cc = ClaimCheckStore(s3, h.metrics)
        self.saga_for = saga_factory(self.settings, infra)
        self.registry = build_registry(self.saga_for, h.clock)
        self.sweeper = returns_deadline_sweeper(h.db, self.saga_for, h.clock, h.metrics)
        auth = Authenticator(self.settings)
        idem = IdempotencyStore(h.clock)

        def retry_step(uow: Any, row: Any) -> bool:
            return self.saga_for(uow).retry_step(uow, row)

        app = create_app(
            self.settings,
            readiness=Readiness(),
            instrument=False,
            routers=[
                returns_router(h.db, self.saga_for, ClaimCheckLabelLinks(self.cc), h.clock, auth, idem),
                saga_ops_router(db=h.db, idempotency=idem, retry_step=retry_step, caller_of=ops_caller(auth)),
            ],
        )
        self.http = TestClient(app, follow_redirects=False)
        self.all: list[Published] = []
        self._k = 0

    def send(
        self, cls: type, body: dict[str, Any], *, producer: str = "x-svc", event_id: str | None = None, corr: str | None = None
    ) -> Outcome:
        rec = self.h.command(cls, body, key=ORDER, producer=producer, event_id=event_id, correlation_id=corr)
        return self.h.deliver(self.registry, rec)

    def out(self) -> list[Published]:
        p = self.h.published()
        self.all += p
        return p

    def last(self, record: str) -> dict[str, Any]:
        return [p for p in self.all if p.type.endswith("." + record)][-1].value

    def deliver_order(self, *, qty: int = 2, unit: int = 12999, fee: int = 0, delivered_days_ago: int = 5) -> None:
        now = self.h.clock.now()
        total = qty * unit + fee
        self.send(
            R.OrderPlaced,
            {
                "orderId": ORDER,
                "customerId": CUSTOMER,
                "lines": [
                    {
                        "lineId": "l-1",
                        "sku": "SKU-1001",
                        "productName": "Trail Running Shoe",
                        "quantity": qty,
                        "unitPrice": {"amountMinor": unit, "currency": "EUR"},
                        "lineTotal": {"amountMinor": qty * unit, "currency": "EUR"},
                    }
                ],
                "total": {"amountMinor": total, "currency": "EUR"},
                "shippingAddress": ADDRESS,
                "contactEmail": "jane.doe@example.com",
                "shippingMethod": "STANDARD",
                "placedAt": now,
            },
            producer="order-svc",
        )
        self.send(
            R.OrderConfirmed,
            {"orderId": ORDER, "reservationId": "r", "paymentId": "pay-1", "fulfilmentId": "f", "confirmedAt": now},
            producer="order-svc",
        )
        self.send(
            R.FulfilmentAccepted,
            {"orderId": ORDER, "fulfilmentId": "f", "warehouseId": "wh-berlin-1", "acceptedAt": now},
            producer="fulfilment-svc",
        )
        at = now - timedelta(days=delivered_days_ago)
        self.send(
            R.OrderDelivered,
            {"orderId": ORDER, "shipmentId": "s-1", "deliveredAt": at, "returnWindowEndsAt": at + timedelta(days=30)},
            producer="order-svc",
        )
        self.out()

    def post_return(
        self, lines: list[tuple[str, int]], reason: str = "CHANGED_MIND", *, key: str | None = None, subject: str = CUSTOMER
    ) -> Any:
        self._k += 1
        body = {"orderId": ORDER, "lines": [{"lineId": i, "quantity": q} for i, q in lines], "reason": reason}
        return self.http.post(
            "/returns", json=body, headers={"Idempotency-Key": key or f"k-{self._k}", "X-Debug-Subject": subject}
        )

    def label(self, return_id: str) -> None:
        cc = self.cc.put("shipping-labels", f"shipping/2026/11/{ORDER}/x.pdf", b"%PDF label", "application/pdf")
        sid = self.last("IssueReturnLabel")["shipmentId"]
        self.send(
            R.ShipmentCreated,
            {
                "orderId": ORDER,
                "shipmentId": sid,
                "direction": "RETURN",
                "carrier": "fake-carrier",
                "trackingNumber": "FC9",
                "label": cc.to_avro(),
                "createdAt": self.h.clock.now(),
                "returnId": return_id,
            },
            producer="shipping-svc",
            corr=return_id,
        )

    def inspect(self, return_id: str, results: list[tuple[int, str]]) -> None:
        self.send(
            R.ReturnReceived,
            {"orderId": ORDER, "returnId": return_id, "receivedAt": self.h.clock.now()},
            producer="fulfilment-svc",
        )
        self.send(
            R.ReturnInspected,
            {
                "orderId": ORDER,
                "returnId": return_id,
                "inspectedAt": self.h.clock.now(),
                "results": [{"lineId": "l-1", "sku": "SKU-1001", "quantity": q, "outcome": o} for q, o in results],
            },
            producer="fulfilment-svc",
        )
        self.out()


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="shipping-labels")
        h = ServiceHarness(
            url=pg_url,
            migrations=MIGRATIONS,
            group="returns-svc",
            serde=AvroSerde(schema_registry),
            clock=clock,
            metrics=metrics_reader[0],
        )
        yield Svc(h, s3)
        h.close()
