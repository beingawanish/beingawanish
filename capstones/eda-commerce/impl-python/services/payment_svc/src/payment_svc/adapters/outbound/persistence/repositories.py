"""Postgres implementation of :class:`PaymentRepository` plus the webhook store."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from payment_svc.adapters.outbound.persistence.models import PaymentAttemptRow, PaymentRow, PspWebhookRow, RefundRow
from payment_svc.domain.payment import (
    CaptureFailure,
    DeclineReason,
    Payment,
    PaymentStatus,
    Refund,
    RefundStatus,
)

_PAYMENT_FIELDS = [f.name for f in fields(Payment)]
_REFUND_FIELDS = [f.name for f in fields(Refund)]


def _payment(row: PaymentRow) -> Payment:
    d = {k: getattr(row, k) for k in _PAYMENT_FIELDS}
    d["status"] = PaymentStatus(d["status"])
    d["decline_reason"] = DeclineReason(d["decline_reason"]) if d["decline_reason"] else None
    d["capture_failure"] = CaptureFailure(d["capture_failure"]) if d["capture_failure"] else None
    return Payment(**d)


def _refund(row: RefundRow) -> Refund:
    d = {k: getattr(row, k) for k in _REFUND_FIELDS}
    d["status"] = RefundStatus(d["status"])
    return Refund(**d)


def _plain(v: Any) -> Any:
    from enum import Enum

    return v.value if isinstance(v, Enum) else v


class SqlPaymentRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, payment_id: str, *, for_update: bool = False) -> Payment | None:
        q = select(PaymentRow).where(PaymentRow.payment_id == payment_id)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        return _payment(row) if row else None

    def save(self, p: Payment, now: datetime) -> None:
        values = {k: _plain(getattr(p, k)) for k in _PAYMENT_FIELDS}
        values["updated_at"] = now
        stmt = pg_insert(PaymentRow).values(created_at=now, **values)
        self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["payment_id"], set_={k: stmt.excluded[k] for k in values if k != "payment_id"}
            )
        )

    def due_reconciliation(self, now: datetime, limit: int) -> list[Payment]:
        rows = (
            self._s.execute(
                select(PaymentRow)
                .where(PaymentRow.status == PaymentStatus.UNKNOWN.value, PaymentRow.next_reconcile_at <= now)
                .order_by(PaymentRow.next_reconcile_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        return [_payment(r) for r in rows]

    def record_attempt(self, payment_id: str, operation: str, outcome: str, now: datetime, detail: str | None = None) -> None:
        self._s.add(PaymentAttemptRow(payment_id=payment_id, operation=operation, outcome=outcome, detail=detail, at=now))
        self._s.flush()

    def get_refund(self, refund_id: str, *, for_update: bool = False) -> Refund | None:
        q = select(RefundRow).where(RefundRow.refund_id == refund_id)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        return _refund(row) if row else None

    def save_refund(self, r: Refund, now: datetime) -> None:
        values = {k: _plain(getattr(r, k)) for k in _REFUND_FIELDS}
        values["updated_at"] = now
        stmt = pg_insert(RefundRow).values(created_at=now, **values)
        self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["refund_id"], set_={k: stmt.excluded[k] for k in values if k != "refund_id"}
            )
        )


class WebhookStore:
    """Store-then-ack (webhooks.yaml rule 3): raw notifications land here; a job applies them."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def store(self, payload: dict[str, Any]) -> None:
        self._s.add(
            PspWebhookRow(
                psp_event_id=payload["pspEventId"],
                event_type=payload["eventType"],
                merchant_reference=payload["merchantReference"],
                payload=payload,
            )
        )
        self._s.flush()

    def claim(self, limit: int) -> list[PspWebhookRow]:
        return list(
            self._s.execute(
                select(PspWebhookRow)
                .where(PspWebhookRow.processed_at.is_(None))
                .order_by(PspWebhookRow.received_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )

    def mark_processed(self, psp_event_id: str, now: datetime) -> None:
        self._s.execute(update(PspWebhookRow).where(PspWebhookRow.psp_event_id == psp_event_id).values(processed_at=now))


class OutboxPublisher:
    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
