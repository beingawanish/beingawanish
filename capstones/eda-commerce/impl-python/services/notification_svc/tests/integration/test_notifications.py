"""notification-svc with real Postgres, its migrations, the consumer processor, the polling relay, the
fake mailer and an S3 API (moto) (checklist §11 notification items)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from contracts_py import records as R
from edacommon.claimcheck import ClaimCheckStore
from edacommon.consumer import ConsumedRecord, Outcome
from edacommon.logging import configure_logging
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde, decode_raw
from edacommon.testing.fakes import counter_value
from edacommon.testing.infra import contract_sql_path, fresh_database, information_schema_columns
from edacommon.testing.service import ServiceHarness
from moto import mock_aws
from notification_svc.adapters.inbound.messaging.handlers import build_registry
from notification_svc.adapters.outbound.mail.fake.mailer import FakeMailer
from notification_svc.adapters.outbound.storage.attachments import ClaimCheckAttachments
from notification_svc.config import Settings
from notification_svc.main import notifications_factory
from sqlalchemy import create_engine

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
EXAMPLES = Path(__file__).resolve().parents[5] / "contracts" / "examples"
ORDER = "0193a1c4-0000-7000-8000-00000000f001"
EMAIL = "jane.doe@example.com"


class Svc:
    def __init__(self, h: ServiceHarness, s3: Any) -> None:
        self.h = h
        self.s3 = s3
        self.mailer = FakeMailer()
        self.cc = ClaimCheckStore(s3, h.metrics)
        infra = Infrastructure(settings=Settings(), clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.registry = build_registry(notifications_factory(infra, self.mailer, ClaimCheckAttachments(self.cc)), h.clock)

    def send(self, cls: type, body: dict[str, Any], *, event_id: str | None = None, producer: str = "order-svc") -> Outcome:
        return self.h.deliver(self.registry, self.h.command(cls, body, key=ORDER, event_id=event_id, producer=producer))

    def placed(self) -> Outcome:
        v = decode_raw("com.edacommerce.order.OrderPlaced", (EXAMPLES / "com.edacommerce.order.OrderPlaced.bin").read_bytes())
        v.pop("envelope")
        v.update(orderId=ORDER, customerId="cust-1")
        return self.send(R.OrderPlaced, v)

    def sent(self) -> list[Any]:
        return [p for p in self.h.published() if p.topic == "notification.events.v1"]


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        for b in ("invoices", "shipping-labels"):
            s3.create_bucket(Bucket=b)
        h = ServiceHarness(
            url=pg_url,
            migrations=MIGRATIONS,
            group="notification-svc",
            serde=AvroSerde(schema_registry),
            clock=clock,
            metrics=metrics_reader[0],
        )
        yield Svc(h, s3)
        h.close()


def confirmed(svc: Svc) -> dict[str, Any]:
    now = svc.h.clock.now()
    return {"orderId": ORDER, "reservationId": "r", "paymentId": "p", "fulfilmentId": "f", "confirmedAt": now}


def invoice(svc: Svc, put: bool = True) -> dict[str, Any]:
    pdf = b"%PDF-1.4 invoice"
    key = f"order/2026/11/{ORDER}/inv-1.pdf"
    cc = svc.cc.put("invoices", key, pdf, "application/pdf") if put else None
    doc = (
        cc.to_avro()
        if cc
        else {"bucket": "invoices", "objectKey": key, "contentType": "application/pdf", "sizeBytes": 16, "sha256": "0" * 64}
    )
    return {
        "orderId": ORDER,
        "invoiceId": "inv-1",
        "invoiceNumber": "INV-2026-000001",
        "total": {"amountMinor": 25998, "currency": "EUR"},
        "document": doc,
        "issuedAt": svc.h.clock.now(),
    }


def test_shared_tables_match_contract_and_orm_matches_migrations(svc: Svc) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from notification_svc.adapters.outbound.persistence.models import Base

    tables = ["outbox", "inbox", "idempotency_key"]
    with fresh_database("contract") as ref:
        e = create_engine(ref)
        with e.begin() as c:
            c.exec_driver_sql(contract_sql_path().read_text())
        e.dispose()
        assert information_schema_columns(svc.h.url, tables) == information_schema_columns(ref, tables)
    e = create_engine(svc.h.url)
    with e.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    e.dispose()
    assert [
        d for d in diff if d[0] in ("add_table", "add_column", "remove_column") and getattr(d[1], "name", "") not in tables
    ] == []


def test_order_confirmed_sends_one_email_and_notification_sent(svc: Svc) -> None:
    assert svc.placed() is Outcome.SUCCESS
    rec = svc.h.command(R.OrderConfirmed, confirmed(svc), key=ORDER, producer="order-svc")
    assert svc.h.deliver(svc.registry, rec) is Outcome.SUCCESS
    (mail,) = svc.mailer.outbox
    assert mail.to == EMAIL and mail.subject == "Your order is confirmed" and mail.text.startswith("Hello Jane Doe,")
    (ev,) = svc.sent()
    v = ev.value
    assert ev.type == "com.edacommerce.notification.NotificationSent" and ev.key == ORDER
    assert v["template"] == "order-confirmed.v1" and v["channel"] == "EMAIL" and v["customerId"] == "cust-1"
    assert v["sourceEventId"] == rec.event_id and ev.envelope["causationId"] == rec.event_id
    assert ev.envelope["producer"] == "notification-svc" and ev.envelope["aggregateType"] == "Notification"
    assert EMAIL not in str(v), "events carry ids, not people"


def test_one_email_per_trigger_under_duplicates_and_reemits(svc: Svc, metrics_reader: Any) -> None:
    svc.placed()
    rec = svc.h.command(R.OrderConfirmed, confirmed(svc), key=ORDER, producer="order-svc")
    for _ in range(3):  # redelivery (same eventId), e.g. chaos-psp-duplicates upstream or a rebalance
        svc.h.deliver(svc.registry, rec)
    assert svc.send(R.OrderConfirmed, confirmed(svc)) is Outcome.SUCCESS  # same fact, new eventId
    assert len(svc.mailer.outbox) == 1 and len(svc.sent()) == 1
    assert counter_value(metrics_reader[1], "eda.consumer.processed", outcome="duplicate") == 2


def test_invoice_email_carries_the_verified_pdf(svc: Svc) -> None:
    svc.placed()
    assert svc.send(R.InvoiceIssued, invoice(svc)) is Outcome.SUCCESS
    (mail,) = svc.mailer.outbox
    (att,) = mail.attachments
    assert att.data == b"%PDF-1.4 invoice" and att.filename == "inv-1.pdf" and att.content_type == "application/pdf"
    (ev,) = svc.sent()
    assert ev.value["attachmentCount"] == 1 and ev.value["template"] == "invoice.v1"


def test_missing_object_is_retried_through_the_retry_topics(svc: Svc) -> None:
    svc.placed()
    assert svc.send(R.InvoiceIssued, invoice(svc, put=False)) is Outcome.RETRY
    assert svc.mailer.outbox == [] and svc.h.producer.on("notification-svc.retry.10s")


def test_tampered_object_goes_to_dlq(svc: Svc) -> None:
    svc.placed()
    body = invoice(svc)
    svc.s3.put_object(Bucket="invoices", Key=body["document"]["objectKey"], Body=b"%PDF-1.4 tampered")
    assert svc.send(R.InvoiceIssued, body) is Outcome.DLQ


def test_expired_attachment_is_skipped_with_a_warning(svc: Svc) -> None:
    svc.placed()
    body = invoice(svc)
    body["document"]["expiresAt"] = svc.h.clock.now() - timedelta(days=1)
    assert svc.send(R.InvoiceIssued, body) is Outcome.SUCCESS
    assert svc.mailer.outbox[0].attachments == ()


def test_return_label_email_has_the_pdf(svc: Svc) -> None:
    svc.placed()
    cc = svc.cc.put("shipping-labels", f"shipping/2026/11/{ORDER}/rs-1.pdf", b"%PDF label", "application/pdf")
    body = {
        "orderId": ORDER,
        "shipmentId": "rs-1",
        "direction": "RETURN",
        "carrier": "fake-carrier",
        "trackingNumber": "FC1",
        "label": cc.to_avro(),
        "createdAt": svc.h.clock.now(),
        "returnId": "ret-1",
    }
    svc.send(R.ShipmentCreated, body, producer="shipping-svc")
    svc.send(R.ShipmentCreated, {**body, "direction": "OUTBOUND", "shipmentId": "s-2"}, producer="shipping-svc")
    (mail,) = svc.mailer.outbox
    assert mail.subject == "Your return label" and mail.attachments[0].data == b"%PDF label"


def test_event_before_contact_waits_and_return_refunds_are_not_double_announced(svc: Svc) -> None:
    refund = {
        "orderId": ORDER,
        "paymentId": "p",
        "refundId": "rf-1",
        "amount": {"amountMinor": 12999, "currency": "EUR"},
        "pspReference": "x",
        "refundedAt": svc.h.clock.now(),
    }
    assert svc.send(R.RefundSucceeded, refund, producer="payment-svc") is Outcome.RETRY  # OrderPlaced not seen yet
    svc.placed()
    assert (
        svc.send(R.RefundSucceeded, {**refund, "refundId": "rf-2", "returnId": "ret-1"}, producer="payment-svc")
        is Outcome.SUCCESS
    )
    assert svc.mailer.outbox == []
    svc.send(
        R.ReturnRefunded,
        {"orderId": ORDER, "returnId": "ret-1", "refundId": "rf-2", "amount": refund["amount"], "refundedAt": svc.h.clock.now()},
        producer="returns-svc",
    )
    assert [m.subject for m in svc.mailer.outbox] == ["Refund of 129.99 EUR for your return"]


def test_unknown_type_and_unknown_enum_are_handled(svc: Svc) -> None:
    rec = ConsumedRecord(
        topic="order.events.v1",
        partition=0,
        offset=1,
        key=b"o",
        value=b"??",
        headers=[("ce_type", b"com.edacommerce.order.OrderArchived"), ("ce_id", b"x")],
    )
    assert svc.h.deliver(svc.registry, rec) is Outcome.IGNORED
    svc.placed()
    body = {
        "orderId": ORDER,
        "shipmentId": "s",
        "direction": "OUTBOUND",
        "code": "UNKNOWN",
        "raisedAt": svc.h.clock.now(),
        "carrierEventId": "c1",
    }
    assert svc.send(R.ShipmentException, body, producer="shipping-svc") is Outcome.SUCCESS
    assert svc.mailer.outbox[0].subject == "A problem with your delivery"


def test_no_pii_in_logs(svc: Svc) -> None:
    buf = io.StringIO()
    configure_logging("notification-svc", stream=buf, level="DEBUG")
    try:
        svc.placed()
        svc.send(R.OrderConfirmed, confirmed(svc))
        svc.send(R.InvoiceIssued, invoice(svc))
    finally:
        configure_logging("notification-svc", fmt="console")
    logs = buf.getvalue()
    assert "notification sent" in logs and ORDER in logs
    assert EMAIL not in logs and "Jane Doe" not in logs and "Invalidenstrasse" not in logs
