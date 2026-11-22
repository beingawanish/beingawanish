"""payment-svc end to end inside the service: command -> PSP -> signed webhook -> store-then-ack ->
processor -> reply, with real Postgres and the polling relay (checklist §11 payment-svc items)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts_py.records import AuthorizePayment, CapturePayment, RefundPayment, VoidPayment
from edacommon.consumer import Outcome
from edacommon.http import Authenticator, Readiness, create_app
from edacommon.runtime import Infrastructure
from edacommon.serde import AvroSerde
from edacommon.testing.fakes import counter_value
from edacommon.testing.service import ServiceHarness
from edacommon.webhooks import sign
from payment_svc.adapters.inbound.http.routes import fake_psp_router, webhook_router
from payment_svc.adapters.inbound.messaging.handlers import build_registry
from payment_svc.adapters.outbound.psp.fake.psp import FakePsp, FakePspConfig, WebhookSender
from payment_svc.config import Settings
from payment_svc.main import wire

pytestmark = pytest.mark.integration
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"
ORDER = "0193a1c4-0000-7000-8000-00000000b001"


class Svc:
    def __init__(self, h: ServiceHarness, settings: Settings) -> None:
        self.h = h
        self.settings = settings
        self.sender = WebhookSender(settings.psp_webhook_url, settings.psp_webhook_secret, send=self._post,
                                    wall_clock=lambda: h.clock.now().timestamp())
        self.psp = FakePsp(FakePspConfig(declineRate=0, timeoutRate=0, duplicateWebhookRate=0, apiLatencyMs=0),
                           self.sender, seed=7)
        infra = Infrastructure(settings=settings, clock=h.clock, metrics=h.metrics, db=h.db, serde=h.serde, outbox=h.outbox)
        self.w = wire(settings, infra, self.psp)
        self.registry = build_registry(self.w.payments_for, h.clock)
        app = create_app(settings, readiness=Readiness(), instrument=False, routers=[
            webhook_router(self.w.receiver, h.clock), fake_psp_router(self.psp, Authenticator(settings))])
        self.http = TestClient(app)
        self.webhook_statuses: list[int] = []

    def _post(self, url: str, headers: dict[str, str], raw: bytes) -> None:
        self.webhook_statuses.append(self.http.post("/webhooks/psp", content=raw, headers=headers).status_code)

    def authorize(self, token: str = "tok_visa_ok", pid: str = "pay-1", event_id: str | None = None) -> Any:
        rec = self.h.command(AuthorizePayment, {"orderId": ORDER, "paymentId": pid, "customerId": "cust-1",
                                                "amount": {"amountMinor": 25998, "currency": "EUR"},
                                                "paymentMethodToken": token}, key=ORDER, event_id=event_id)
        assert self.h.deliver(self.registry, rec) is Outcome.SUCCESS
        return rec

    def settle(self) -> list[Any]:
        self.sender.flush()
        self.w.processor.run_once()
        return [p for p in self.h.published() if p.topic == "payment.events.v1"]


@pytest.fixture
def svc(pg_url: str, schema_registry: Any, clock: Any, metrics_reader: Any) -> Iterator[Svc]:
    h = ServiceHarness(url=pg_url, migrations=MIGRATIONS, group="payment-svc", serde=AvroSerde(schema_registry),
                       clock=clock, metrics=metrics_reader[0])
    yield Svc(h, Settings())
    h.close()


def types(pubs: list[Any]) -> list[str]:
    return [p.type.rsplit(".", 1)[1] for p in pubs]


def test_authorize_happy_path_reply_has_envelope_and_causation(svc: Svc) -> None:
    rec = svc.authorize()
    assert svc.h.published() == [], "nothing until the PSP webhook arrives"
    (auth,) = svc.settle()
    assert auth.type.endswith("PaymentAuthorized") and auth.key == ORDER
    assert auth.value["amount"] == {"amountMinor": 25998, "currency": "EUR"} and auth.value["pspReference"].startswith("psp_")
    env = auth.envelope
    assert env["producer"] == "payment-svc" and env["partitionKey"] == ORDER and env["correlationId"] == ORDER
    assert env["causationId"] == rec.event_id, "async reply is caused by the command that asked for it"
    assert env["aggregateType"] == "Payment" and env["aggregateId"] == "pay-1"


def test_decline(svc: Svc) -> None:
    svc.authorize("tok_decline")
    (d,) = svc.settle()
    assert d.type.endswith("PaymentDeclined") and d.value["reason"] == "CARD_DECLINED"


def test_duplicate_webhooks_three_times_one_event(svc: Svc, metrics_reader: Any) -> None:
    svc.authorize("tok_dup_webhook")
    assert types(svc.settle()) == ["PaymentAuthorized"]
    assert svc.webhook_statuses == [200, 200, 200], "duplicates answer 200"
    reader = metrics_reader[1]
    assert counter_value(reader, "eda.webhook.received", source="psp", outcome="accepted") == 1
    assert counter_value(reader, "eda.webhook.received", source="psp", outcome="duplicate") == 2


def test_timeout_reconciles_to_authorized_and_late_webhook_is_noop(svc: Svc) -> None:
    svc.psp.config = svc.psp.config.merged({"timeoutRate": 1.0})
    svc.authorize("tok_ordinary")
    svc.w.processor.run_once()
    assert svc.h.published() == []
    svc.h.clock.advance(timedelta(seconds=16))
    assert svc.w.reconciler.run_once() == 1
    assert types(svc.h.published()) == ["PaymentAuthorized"]
    assert types(svc.settle()) == [], "the webhook that follows changes nothing"


def test_timeout_to_psp_timeout_with_void_then_late_success_is_voided(svc: Svc) -> None:
    svc.authorize("tok_timeout")
    for _ in range(8):  # every 15 s for 2 minutes
        svc.h.clock.advance(timedelta(seconds=15))
        svc.w.reconciler.run_once()
    (d,) = [p for p in svc.h.published()]
    assert d.type.endswith("PaymentDeclined") and d.value["reason"] == "PSP_TIMEOUT"
    assert ("void", "pay-1") in svc.psp.calls
    # Later the PSP sends authorization.succeeded after all: void it; the saga hears nothing.
    svc.psp.calls.clear()
    body = json.dumps({"pspEventId": "evt-late", "eventType": "authorization.succeeded", "pspPaymentId": "psp-late",
                       "merchantReference": "pay-1", "occurredAt": "2026-11-18T11:10:00.000Z"}).encode()
    ts = str(int(svc.h.clock.now().timestamp()))
    assert svc.http.post("/webhooks/psp", content=body, headers={
        "X-Webhook-Timestamp": ts, "X-Psp-Signature": sign("dev-psp-secret", ts, body)}).status_code == 200
    assert types(svc.settle()) == []
    assert ("void", "pay-1") in svc.psp.calls


def test_bad_signature_and_stale_timestamp_are_401(svc: Svc) -> None:
    body = b'{"pspEventId":"e1","eventType":"authorization.succeeded","pspPaymentId":"x","merchantReference":"p","occurredAt":"2026-11-18T10:00:00Z"}'
    ts = str(int(svc.h.clock.now().timestamp()))
    r = svc.http.post("/webhooks/psp", content=body, headers={"X-Webhook-Timestamp": ts, "X-Psp-Signature": "deadbeef"})
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    old = str(int(svc.h.clock.now().timestamp()) - 600)
    r = svc.http.post("/webhooks/psp", content=body, headers={"X-Webhook-Timestamp": old,
                                                               "X-Psp-Signature": sign("dev-psp-secret", old, body)})
    assert r.status_code == 401
    r = svc.http.post("/webhooks/psp", content=b"{", headers={"X-Webhook-Timestamp": ts,
                                                               "X-Psp-Signature": sign("dev-psp-secret", ts, b"{")})
    assert r.status_code == 400


def test_resent_authorize_reemits_original_reply_without_new_psp_charge(svc: Svc) -> None:
    svc.authorize()
    (first,) = svc.settle()
    resend = svc.authorize()  # new eventId, same paymentId
    (again,) = [p for p in svc.h.published()]
    assert again.type == first.type and again.value["authorizedAt"] == first.value["authorizedAt"]
    assert again.envelope["causationId"] == resend.event_id
    assert svc.psp.calls.count(("authorize", "pay-1")) == 1 and svc.psp.charges("pay-1") == 1


def test_capture_then_resend_and_capture_fails_token(svc: Svc) -> None:
    svc.authorize()
    svc.settle()
    cap = svc.h.command(CapturePayment, {"orderId": ORDER, "paymentId": "pay-1",
                                         "amount": {"amountMinor": 25998, "currency": "EUR"}}, key=ORDER)
    svc.h.deliver(svc.registry, cap)
    assert types(svc.settle()) == ["PaymentCaptured"]
    svc.h.deliver(svc.registry, svc.h.command(CapturePayment, {"orderId": ORDER, "paymentId": "pay-1",
                                                               "amount": {"amountMinor": 25998, "currency": "EUR"}}, key=ORDER))
    assert types(svc.settle()) == ["PaymentCaptured"]
    assert svc.psp.calls.count(("capture", "pay-1")) == 1

    svc.authorize("tok_capture_fails", pid="pay-2")
    svc.settle()
    svc.h.deliver(svc.registry, svc.h.command(CapturePayment, {"orderId": ORDER, "paymentId": "pay-2",
                                                               "amount": {"amountMinor": 25998, "currency": "EUR"}}, key=ORDER))
    (f,) = svc.settle()
    assert f.type.endswith("PaymentCaptureFailed") and f.value["reason"] == "AUTHORIZATION_EXPIRED" and f.value["retryable"] is False


def test_void_and_void_again(svc: Svc) -> None:
    svc.authorize()
    svc.settle()
    for _ in range(2):
        svc.h.deliver(svc.registry, svc.h.command(VoidPayment, {"orderId": ORDER, "paymentId": "pay-1",
                                                                "reason": "RESERVATION_EXPIRED"}, key=ORDER))
    voided = svc.settle()
    assert types(voided) == ["PaymentVoided", "PaymentVoided"] and voided[0].value["voidedAt"] == voided[1].value["voidedAt"]
    # void for a payment never seen (authorise lost) answers voided too
    svc.h.deliver(svc.registry, svc.h.command(VoidPayment, {"orderId": ORDER, "paymentId": "pay-x", "reason": "t"}, key=ORDER))
    assert types(svc.settle()) == ["PaymentVoided"]


def test_void_after_capture_goes_to_dlq(svc: Svc, metrics_reader: Any) -> None:
    svc.authorize()
    svc.settle()
    svc.h.deliver(svc.registry, svc.h.command(CapturePayment, {"orderId": ORDER, "paymentId": "pay-1",
                                                               "amount": {"amountMinor": 25998, "currency": "EUR"}}, key=ORDER))
    svc.settle()
    out = svc.h.deliver(svc.registry, svc.h.command(VoidPayment, {"orderId": ORDER, "paymentId": "pay-1", "reason": "x"}, key=ORDER))
    assert out is Outcome.DLQ


def test_refund_once_per_refund_id(svc: Svc) -> None:
    svc.authorize()
    svc.settle()
    svc.h.deliver(svc.registry, svc.h.command(CapturePayment, {"orderId": ORDER, "paymentId": "pay-1",
                                                               "amount": {"amountMinor": 25998, "currency": "EUR"}}, key=ORDER))
    svc.settle()
    body = {"orderId": ORDER, "paymentId": "pay-1", "refundId": "rf-1", "returnId": "ret-1",
            "amount": {"amountMinor": 12999, "currency": "EUR"}, "reason": "RETURN"}
    svc.h.deliver(svc.registry, svc.h.command(RefundPayment, body, key=ORDER, producer="returns-svc"))
    assert types(svc.settle()) == ["RefundSucceeded"]
    svc.h.deliver(svc.registry, svc.h.command(RefundPayment, body, key=ORDER, producer="returns-svc"))
    (again,) = svc.settle()
    assert again.type.endswith("RefundSucceeded") and again.value["amount"]["amountMinor"] == 12999
    assert svc.psp.calls.count(("refund", "rf-1")) == 1


def test_fake_psp_admin_api(svc: Svc) -> None:
    r = svc.http.get("/admin/fakes/psp")
    assert r.status_code == 200 and set(r.json()) == {"declineRate", "timeoutRate", "duplicateWebhookRate",
                                                      "webhookDelayMs", "slowWebhookMs", "apiLatencyMs"}
    r = svc.http.put("/admin/fakes/psp", json={"declineRate": 0.5})
    assert r.status_code == 200 and r.json()["declineRate"] == 0.5
    assert svc.http.put("/admin/fakes/psp", json={"declineRate": 2}).status_code == 400
