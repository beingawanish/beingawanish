"""Inbound webhooks: HMAC verification, timestamp tolerance, inbox dedupe, store-then-ack
(webhooks.yaml, ADR-0006, ADR-0013).

The receiving endpoint does four things and nothing else, then answers 200 in well under a second:

1. verify ``hex(HMAC-SHA256(secret, "<timestamp>.<raw body>"))`` in constant time; reject if the
   timestamp is more than 300 s away from now -> 401;
2. parse the body -> 400 if it is not JSON;
3. insert the provider event id into ``inbox`` (``consumer = 'psp-webhook'`` / ``'carrier-webhook'``);
   a conflict means a duplicate -> 200 and stop;
4. store the raw payload (service callback) in the same transaction -> 200.

Domain processing happens afterwards from the stored row, so a slow database or a slow handler never
causes provider retries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from edacommon.db import Database
from edacommon.inbox import try_insert
from edacommon.metrics import EdaMetrics

TOLERANCE_S = 300


def sign(secret: str, timestamp: int | str, raw_body: bytes) -> str:
    msg = f"{timestamp}.".encode() + raw_body
    return hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def verify(
    secret: str, timestamp: str | None, raw_body: bytes, signature: str | None, now: datetime, tolerance_s: int = TOLERANCE_S
) -> bool:
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(now.timestamp() - ts) > tolerance_s:
        return False
    expected = sign(secret, ts, raw_body)
    return hmac.compare_digest(expected, signature.strip().lower())


class WebhookOutcome(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class WebhookResult:
    outcome: WebhookOutcome
    status: int
    detail: str = ""


class WebhookReceiver:
    def __init__(
        self,
        *,
        db: Database,
        source: str,
        consumer: str,
        secret: str,
        metrics: EdaMetrics,
        event_id_of: Callable[[dict[str, Any]], str],
        event_type_of: Callable[[dict[str, Any]], str],
        store: Callable[[Session, dict[str, Any], bytes], None],
        on_stored: Callable[[], None] | None = None,
    ) -> None:
        self._db = db
        self._source = source
        self._consumer = consumer
        self._secret = secret
        self._metrics = metrics
        self._event_id_of = event_id_of
        self._event_type_of = event_type_of
        self._store = store
        self._on_stored = on_stored

    def receive(self, *, raw_body: bytes, timestamp: str | None, signature: str | None, now: datetime) -> WebhookResult:
        if not verify(self._secret, timestamp, raw_body, signature, now):
            self._metrics.webhook(source=self._source, outcome=WebhookOutcome.REJECTED)
            return WebhookResult(WebhookOutcome.REJECTED, 401, "bad signature or stale timestamp")
        try:
            payload = json.loads(raw_body)
            event_id = self._event_id_of(payload)
            event_type = self._event_type_of(payload)
        except (ValueError, KeyError, TypeError) as exc:
            self._metrics.webhook(source=self._source, outcome=WebhookOutcome.REJECTED)
            return WebhookResult(WebhookOutcome.REJECTED, 400, f"unparseable body: {exc}")
        with self._db.unit_of_work() as uow:
            if not try_insert(uow.session, message_id=event_id, consumer=self._consumer, message_type=event_type):
                self._metrics.webhook(source=self._source, outcome=WebhookOutcome.DUPLICATE)
                return WebhookResult(WebhookOutcome.DUPLICATE, 200)
            self._store(uow.session, payload, raw_body)
            if self._on_stored:
                uow.after_commit(self._on_stored)
        self._metrics.webhook(source=self._source, outcome=WebhookOutcome.ACCEPTED)
        return WebhookResult(WebhookOutcome.ACCEPTED, 200)
