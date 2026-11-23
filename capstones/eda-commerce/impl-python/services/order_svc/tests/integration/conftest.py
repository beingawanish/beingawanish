from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.consumer import Outcome
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde, decode_raw
from edacommon.testing.service import Published, ServiceHarness
from moto import mock_aws
from order_svc.adapters.inbound.messaging.handlers import build_registry
from order_svc.adapters.outbound.documents.store import ClaimCheckDocuments
from order_svc.config import Settings
from order_svc.main import saga_factory

MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
EXAMPLES = Path(__file__).resolve().parents[5] / "contracts" / "examples"
ORDER = "0193a1c4-0000-7000-8000-00000000c001"


def checkout_body(order_id: str = ORDER, token: str = "tok_visa_ok") -> dict[str, Any]:
    v = decode_raw(
        "com.edacommerce.checkout.CheckoutSubmitted", (EXAMPLES / "com.edacommerce.checkout.CheckoutSubmitted.bin").read_bytes()
    )
    v.pop("envelope")
    v.update(orderId=order_id, paymentMethodToken=token, customerId="cust-1")
    line = v["lines"][0]
    line.update(
        quantity=2, unitPrice={"amountMinor": 12999, "currency": "EUR"}, lineTotal={"amountMinor": 25998, "currency": "EUR"}
    )
    v["total"] = {"amountMinor": 25998, "currency": "EUR"}
    return v


class Svc:
    def __init__(self, h: ServiceHarness, s3: Any) -> None:
        self.h = h
        self.s3 = s3
        self.settings = Settings()
        infra = Infrastructure(settings=self.settings, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.cc = ClaimCheckStore(s3, h.metrics)
        self.documents = ClaimCheckDocuments(self.cc)
        self.saga_for = saga_factory(self.settings, infra, self.documents)
        self.registry = build_registry(self.saga_for, h.clock)
        self.all: list[Published] = []

    def send(
        self, cls: type, body: dict[str, Any], *, key: str = ORDER, producer: str = "x-svc", event_id: str | None = None
    ) -> Outcome:
        return self.h.deliver(self.registry, self.h.command(cls, body, key=key, producer=producer, event_id=event_id))

    def out(self) -> list[Published]:
        p = self.h.published()
        self.all += p
        return p

    def last_command(self, record: str) -> dict[str, Any]:
        return [p for p in self.all if p.type.endswith("." + record)][-1].value


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="invoices")
        h = ServiceHarness(
            url=pg_url,
            migrations=MIGRATIONS,
            group="order-svc",
            serde=AvroSerde(schema_registry),
            clock=clock,
            metrics=metrics_reader[0],
        )
        yield Svc(h, s3)
        h.close()


def drive_to_delivered(svc: Svc, order_id: str = ORDER) -> None:
    """Feed the replies participants would send, matched to the ids the saga minted."""
    svc.send(R.CheckoutSubmitted, checkout_body(order_id), key=order_id, producer="checkout-svc")
    svc.out()
    rid = svc.last_command("ReserveStock")["reservationId"]
    exp = svc.h.clock.now()
    svc.send(
        R.StockReserved,
        {"orderId": order_id, "reservationId": rid, "lines": [{"sku": "SKU-1001", "quantity": 2}], "expiresAt": exp},
        key=order_id,
    )
    svc.out()
    pid = svc.last_command("AuthorizePayment")["paymentId"]
    svc.send(
        R.PaymentAuthorized,
        {
            "orderId": order_id,
            "paymentId": pid,
            "pspReference": "psp1",
            "amount": {"amountMinor": 25998, "currency": "EUR"},
            "authorizedAt": exp,
            "authorizationExpiresAt": exp,
        },
        key=order_id,
    )
    svc.out()
    svc.send(R.ReservationCommitted, {"orderId": order_id, "reservationId": rid, "committedAt": exp}, key=order_id)
    svc.out()
    fid = svc.last_command("RequestFulfilment")["fulfilmentId"]
    svc.send(
        R.FulfilmentAccepted, {"orderId": order_id, "fulfilmentId": fid, "warehouseId": "wh-1", "acceptedAt": exp}, key=order_id
    )
    cc = {"bucket": "packing-manifests", "objectKey": "k", "contentType": "application/json", "sizeBytes": 1, "sha256": "0" * 64}
    svc.send(
        R.OrderPacked,
        {
            "orderId": order_id,
            "fulfilmentId": fid,
            "warehouseId": "wh-1",
            "parcels": [],
            "manifest": cc,
            "shipTo": checkout_body()["shippingAddress"],
            "shippingMethod": "STANDARD",
            "packedAt": exp,
        },
        key=order_id,
    )
    svc.send(
        R.ShipmentCreated,
        {
            "orderId": order_id,
            "shipmentId": "ship-1",
            "direction": "OUTBOUND",
            "fulfilmentId": fid,
            "carrier": "fake-carrier",
            "trackingNumber": "FC1",
            "label": {**cc, "bucket": "shipping-labels"},
            "createdAt": exp,
        },
        key=order_id,
    )
    svc.send(
        R.OrderDispatched, {"orderId": order_id, "fulfilmentId": fid, "shipmentId": "ship-1", "dispatchedAt": exp}, key=order_id
    )
    svc.out()
    svc.send(
        R.PaymentCaptured,
        {
            "orderId": order_id,
            "paymentId": pid,
            "amount": {"amountMinor": 25998, "currency": "EUR"},
            "pspReference": "psp1",
            "capturedAt": exp,
        },
        key=order_id,
    )
    svc.out()
    svc.send(
        R.ShipmentDelivered,
        {"orderId": order_id, "shipmentId": "ship-1", "direction": "OUTBOUND", "carrierEventId": "c3", "deliveredAt": exp},
        key=order_id,
    )
    svc.out()
