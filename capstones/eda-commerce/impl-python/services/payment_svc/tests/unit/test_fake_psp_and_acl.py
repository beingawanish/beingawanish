"""The fake PSP's deterministic tokens and the ACL mapping (admin.yaml FakePspConfig, webhooks.yaml)."""

from __future__ import annotations

import json

import pytest
from payment_svc.adapters.outbound.psp.acl import outcome_from_notification
from payment_svc.adapters.outbound.psp.fake.psp import FakePsp, FakePspConfig, WebhookSender
from payment_svc.application.ports import PspTimeout
from payment_svc.domain.payment import CaptureFailure, DeclineReason, OutcomeKind


class Collect:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def __call__(self, url: str, headers: dict[str, str], raw: bytes) -> None:
        assert headers["X-Psp-Signature"] and headers["X-Webhook-Timestamp"]
        self.sent.append(json.loads(raw))


def psp(**cfg: object) -> tuple[FakePsp, WebhookSender, Collect]:
    c = Collect()
    sender = WebhookSender("http://x/webhooks/psp", "s", send=c)
    base = {"declineRate": 0.0, "timeoutRate": 0.0, "duplicateWebhookRate": 0.0, "apiLatencyMs": 0}
    base.update(cfg)
    return FakePsp(FakePspConfig().merged(base), sender, seed=1), sender, c


@pytest.mark.parametrize(
    ("token", "event", "code"),
    [
        ("tok_visa_ok", "authorization.succeeded", None),
        ("tok_decline", "authorization.failed", "card_declined"),
        ("tok_insufficient_funds", "authorization.failed", "insufficient_funds"),
        ("tok_fraud", "authorization.failed", "fraud_suspected"),
        ("tok_slow", "authorization.succeeded", None),
        ("tok_capture_fails", "authorization.succeeded", None),
    ],
)
def test_magic_tokens(token: str, event: str, code: str | None) -> None:
    p, sender, c = psp()
    assert p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token=token).kind is OutcomeKind.PENDING
    sender.flush()
    (n,) = c.sent
    assert n["eventType"] == event and n["failureCode"] == code and n["merchantReference"] == "p1"


def test_timeout_token_is_never_found_and_void_is_safe() -> None:
    p, sender, c = psp()
    with pytest.raises(PspTimeout):
        p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_timeout")
    with pytest.raises(PspTimeout):
        p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_timeout")
    assert p.lookup(payment_id="p1").kind is OutcomeKind.NOT_FOUND
    assert p.void(payment_id="p1", psp_payment_id=None).kind is OutcomeKind.VOIDED
    assert sender.flush() == 0


def test_duplicate_webhooks_reuse_the_event_id() -> None:
    p, sender, c = psp()
    p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_dup_webhook")
    sender.flush()
    assert len(c.sent) == 3 and len({n["pspEventId"] for n in c.sent}) == 1


def test_idempotent_authorize_replays_without_new_charge() -> None:
    p, sender, c = psp()
    p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_visa_ok")
    again = p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_visa_ok")
    assert again.kind is OutcomeKind.AUTHORIZED
    sender.flush()
    assert len(c.sent) == 1 and p.charges("p1") == 1


def test_random_timeout_still_processes_and_reconciles_to_authorized() -> None:
    p, sender, c = psp(timeoutRate=1.0)
    with pytest.raises(PspTimeout):
        p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_other")
    assert p.lookup(payment_id="p1").kind is OutcomeKind.AUTHORIZED


def test_capture_fails_token() -> None:
    p, sender, c = psp()
    p.authorize(payment_id="p1", amount_minor=100, currency="EUR", token="tok_capture_fails")
    p.capture(payment_id="p1", psp_payment_id=None, amount_minor=100, currency="EUR")
    sender.flush()
    assert [n["eventType"] for n in c.sent] == ["authorization.succeeded", "capture.failed"]
    ref, o = outcome_from_notification(c.sent[1])
    assert o.capture_failure is CaptureFailure.AUTHORIZATION_EXPIRED and not o.retryable


def test_acl_mapping() -> None:
    base = {"merchantReference": "p1", "pspPaymentId": "psp1", "occurredAt": "2026-11-18T10:00:00.000Z"}
    assert (
        outcome_from_notification({**base, "eventType": "authorization.failed", "failureCode": "fraud_suspected"})[
            1
        ].decline_reason
        is DeclineReason.FRAUD_SUSPECTED
    )
    assert outcome_from_notification({**base, "eventType": "capture.failed", "failureCode": "processing_error"})[1].retryable
    with pytest.raises(ValueError, match="unknown PSP event"):
        outcome_from_notification({**base, "eventType": "chargeback.opened"})


def test_config_merge_ignores_unknown_keys() -> None:
    cfg = FakePspConfig().merged({"declineRate": 0.5, "nonsense": 1})
    assert cfg.declineRate == 0.5 and cfg.timeoutRate == 0.02
