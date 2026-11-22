"""The fake PSP (admin.yaml ``FakePspConfig``): an outbound adapter behind the same port a real PSP
client would implement. It keeps its own state, is idempotent per merchant reference (our paymentId /
refundId), answers authorise/capture asynchronously by signed webhook, and misbehaves on purpose.

Magic tokens are deterministic:

==========================  =====================================================================
``tok_visa_ok``             authorised (webhook after ``webhookDelayMs``)
``tok_decline``             ``authorization.failed`` / ``card_declined``
``tok_insufficient_funds``  ``authorization.failed`` / ``insufficient_funds``
``tok_fraud``               ``authorization.failed`` / ``fraud_suspected``
``tok_timeout``             the API call times out and the PSP never saw the request (no webhook,
                            lookups find nothing): reconciliation ends in void + ``PSP_TIMEOUT``
``tok_slow``                authorised, webhook after ``slowWebhookMs``
``tok_dup_webhook``         authorised, every webhook sent 3 times with the same ``pspEventId``
``tok_capture_fails``       authorised; capture fails with ``authorization_expired``
==========================  =====================================================================

Other tokens follow the probabilities: ``declineRate``; ``timeoutRate`` (the answer is lost but the
PSP *did* authorise: reconciliation or the late webhook resolves it); ``duplicateWebhookRate``
(webhooks sent twice).
"""

from __future__ import annotations

import heapq
import json
import random
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime

from edacommon.ids import new_id, rfc3339
from edacommon.logging import get_logger
from edacommon.webhooks import sign
from payment_svc.application.ports import PspTimeout
from payment_svc.domain.payment import OutcomeKind, PspOutcome

log = get_logger(__name__)


@dataclass(frozen=True)
class FakePspConfig:
    declineRate: float = 0.05  # noqa: N815 - API names (admin.yaml)
    timeoutRate: float = 0.02  # noqa: N815
    duplicateWebhookRate: float = 0.1  # noqa: N815
    webhookDelayMs: int = 300  # noqa: N815
    slowWebhookMs: int = 90000  # noqa: N815
    apiLatencyMs: int = 80  # noqa: N815

    def merged(self, patch: dict[str, object]) -> FakePspConfig:
        allowed = {k: v for k, v in patch.items() if k in asdict(self)}
        return replace(self, **allowed)  # type: ignore[arg-type]


@dataclass
class _FakePayment:
    psp_payment_id: str
    token: str
    amount_minor: int
    currency: str
    status: str                  # pending | authorized | declined | captured | voided
    failure: str | None = None
    duplicates: int = 1
    events: list[str] = field(default_factory=list)


class WebhookSender:
    """Delivers signed notifications after a delay (a heap and one thread). Tests pass ``send``."""

    def __init__(self, url: str, secret: str, send: Callable[[str, dict[str, str], bytes], None] | None = None,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._wall_clock = wall_clock
        self._url = url
        self._secret = secret
        self._send = send or self._http_send
        self._heap: list[tuple[float, int, bytes]] = []
        self._seq = 0
        self._cv = threading.Condition()
        self._stop = False

    def schedule(self, delay_ms: int, body: dict[str, object], copies: int = 1) -> None:
        raw = json.dumps(body, separators=(",", ":")).encode()
        with self._cv:
            for i in range(copies):
                self._seq += 1
                heapq.heappush(self._heap, (time.monotonic() + delay_ms / 1000 + i * 0.05, self._seq, raw))
            self._cv.notify()

    def due(self, *, force: bool = False) -> list[bytes]:
        now = time.monotonic()
        out = []
        with self._cv:
            while self._heap and (force or self._heap[0][0] <= now):
                out.append(heapq.heappop(self._heap)[2])
        return out

    def deliver(self, raw: bytes) -> None:
        ts = str(int(self._wall_clock()))
        headers = {"Content-Type": "application/json", "X-Webhook-Timestamp": ts,
                   "X-Psp-Signature": sign(self._secret, ts, raw)}
        self._send(self._url, headers, raw)

    def flush(self) -> int:
        """Deliver everything scheduled, now (tests)."""
        items = self.due(force=True)
        for raw in items:
            self.deliver(raw)
        return len(items)

    def _http_send(self, url: str, headers: dict[str, str], raw: bytes) -> None:
        import httpx

        for attempt in range(5):  # a real PSP retries until it sees a 2xx
            try:
                r = httpx.post(url, content=raw, headers=headers, timeout=10)
                if r.status_code < 300 or r.status_code in (400, 401):
                    return
            except httpx.HTTPError as exc:
                log.warning("fake PSP webhook delivery failed", attempt=attempt, error=exc)
            time.sleep(2 ** attempt)

    def run(self) -> None:
        while True:
            with self._cv:
                if self._stop:
                    return
                timeout = (self._heap[0][0] - time.monotonic()) if self._heap else 1.0
                if timeout > 0:
                    self._cv.wait(min(timeout, 1.0))
            for raw in self.due():
                self.deliver(raw)

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()


class FakePsp:
    """Implements :class:`payment_svc.application.ports.PspGateway`."""

    name = "fake-psp"

    def __init__(self, config: FakePspConfig, sender: WebhookSender, *, seed: int | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config
        self._sender = sender
        self._rng = random.Random(seed)  # noqa: S311 - simulation, not crypto
        self._sleep = sleep
        self._lock = threading.Lock()
        self._payments: dict[str, _FakePayment] = {}
        self._refunds: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []

    # ------------------------------------------------------------------------------ internals
    def _latency(self) -> None:
        if self.config.apiLatencyMs:
            self._sleep(self.config.apiLatencyMs / 1000)

    def _notify(self, kind: str, ref: str, fp: _FakePayment, failure: str | None = None, delay_ms: int | None = None) -> None:
        event_id = f"evt_{new_id()}"
        fp.events.append(event_id)
        body: dict[str, object] = {
            "pspEventId": event_id, "eventType": kind, "pspPaymentId": fp.psp_payment_id, "merchantReference": ref,
            "amount": {"amountMinor": fp.amount_minor, "currency": fp.currency}, "failureCode": failure,
            "occurredAt": rfc3339(datetime.now(UTC)),
        }
        delay = self.config.webhookDelayMs if delay_ms is None else delay_ms
        self._sender.schedule(delay, body, copies=fp.duplicates)

    def _result(self, fp: _FakePayment) -> PspOutcome:
        kind = {"authorized": OutcomeKind.AUTHORIZED, "captured": OutcomeKind.CAPTURED,
                "voided": OutcomeKind.VOIDED}.get(fp.status, OutcomeKind.PENDING)
        return PspOutcome(kind, psp_payment_id=fp.psp_payment_id, psp_reference=fp.psp_payment_id)

    # ---------------------------------------------------------------------------------- port
    def authorize(self, *, payment_id: str, amount_minor: int, currency: str, token: str) -> PspOutcome:
        self._latency()
        with self._lock:
            self.calls.append(("authorize", payment_id))
            fp = self._payments.get(payment_id)
            if fp is not None:
                # Idempotency-Key replay: same answer, no new charge.
                if fp.status == "declined":
                    from payment_svc.adapters.outbound.psp.acl import outcome_from_notification

                    return outcome_from_notification({"eventType": "authorization.failed", "merchantReference": payment_id,
                                                      "pspPaymentId": fp.psp_payment_id, "failureCode": fp.failure})[1]
                if fp.status == "lost":
                    raise PspTimeout("fake PSP: no answer")
                return self._result(fp)
            fp = _FakePayment(psp_payment_id=f"psp_{new_id()}", token=token, amount_minor=amount_minor,
                              currency=currency, status="pending")
            if token == "tok_dup_webhook" or (token not in _MAGIC and self._rng.random() < self.config.duplicateWebhookRate):
                fp.duplicates = 3 if token == "tok_dup_webhook" else 2
            self._payments[payment_id] = fp
            if token == "tok_timeout":
                fp.status = "lost"   # the request never reached the PSP's ledger
                raise PspTimeout("fake PSP: no answer within 5 s")
            failure = _DECLINES.get(token)
            if failure is None and token not in _MAGIC and self._rng.random() < self.config.declineRate:
                failure = "card_declined"
            if failure:
                fp.status, fp.failure = "declined", failure
                self._notify("authorization.failed", payment_id, fp, failure)
            else:
                fp.status = "authorized"
                delay = self.config.slowWebhookMs if token == "tok_slow" else None
                self._notify("authorization.succeeded", payment_id, fp, delay_ms=delay)
            if token not in _MAGIC and self._rng.random() < self.config.timeoutRate:
                raise PspTimeout("fake PSP: answer lost (the PSP did process it)")
            return PspOutcome(OutcomeKind.PENDING, psp_payment_id=fp.psp_payment_id)

    def capture(self, *, payment_id: str, psp_payment_id: str | None, amount_minor: int, currency: str) -> PspOutcome:
        self._latency()
        with self._lock:
            self.calls.append(("capture", payment_id))
            fp = self._payments.get(payment_id)
            if fp is None or fp.status not in ("authorized", "captured", "capture_failed"):
                return PspOutcome(OutcomeKind.CAPTURE_FAILED, retryable=False)
            if fp.status == "captured":
                return self._result(fp)
            if fp.token == "tok_capture_fails":
                fp.status = "capture_failed"
                self._notify("capture.failed", payment_id, fp, "authorization_expired")
                return PspOutcome(OutcomeKind.PENDING, psp_payment_id=fp.psp_payment_id)
            fp.status = "captured"
            self._notify("capture.succeeded", payment_id, fp)
            return PspOutcome(OutcomeKind.PENDING, psp_payment_id=fp.psp_payment_id)

    def void(self, *, payment_id: str, psp_payment_id: str | None) -> PspOutcome:
        self._latency()
        with self._lock:
            self.calls.append(("void", payment_id))
            fp = self._payments.get(payment_id)
            if fp is None or fp.status == "lost":
                # Voiding something that does not exist is safe and answers "voided".
                return PspOutcome(OutcomeKind.VOIDED)
            if fp.status in ("authorized", "pending", "declined", "voided"):
                fp.status = "voided"
                return PspOutcome(OutcomeKind.VOIDED, psp_payment_id=fp.psp_payment_id)
            return PspOutcome(OutcomeKind.PENDING, psp_payment_id=fp.psp_payment_id)

    def refund(self, *, refund_id: str, payment_id: str, psp_payment_id: str | None, amount_minor: int,
               currency: str) -> PspOutcome:
        self._latency()
        with self._lock:
            self.calls.append(("refund", refund_id))
            fp = self._payments.get(payment_id)
            if refund_id in self._refunds:
                return PspOutcome(OutcomeKind.REFUNDED, psp_reference=self._refunds[refund_id])
            if fp is None or fp.status != "captured":
                return PspOutcome(OutcomeKind.REFUND_FAILED, refund_failure="not_captured", retryable=False)
            self._refunds[refund_id] = f"rf_{new_id()}"
            refund_fp = replace(fp, amount_minor=amount_minor, duplicates=1, events=[])
            self._notify("refund.succeeded", refund_id, refund_fp)
            return PspOutcome(OutcomeKind.PENDING)

    def lookup(self, *, payment_id: str) -> PspOutcome:
        self._latency()
        with self._lock:
            self.calls.append(("lookup", payment_id))
            fp = self._payments.get(payment_id)
            if fp is None or fp.status in ("lost", "pending"):
                return PspOutcome(OutcomeKind.NOT_FOUND)
            if fp.status == "declined":
                from payment_svc.adapters.outbound.psp.acl import outcome_from_notification

                return outcome_from_notification({"eventType": "authorization.failed", "merchantReference": payment_id,
                                                  "pspPaymentId": fp.psp_payment_id, "failureCode": fp.failure})[1]
            return self._result(fp)

    # ------------------------------------------------------------------------------- test aids
    def charges(self, payment_id: str) -> int:
        """How many distinct authorisations the PSP holds for a merchant reference (always 0 or 1)."""
        return 1 if payment_id in self._payments else 0


_DECLINES = {"tok_decline": "card_declined", "tok_insufficient_funds": "insufficient_funds", "tok_fraud": "fraud_suspected"}
_MAGIC = {"tok_visa_ok", "tok_timeout", "tok_slow", "tok_dup_webhook", "tok_capture_fails", *_DECLINES}
