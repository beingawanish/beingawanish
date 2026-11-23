"""Postgres implementation of :class:`ShipmentRepository`, the tracking-event store, and the outbox
EventPublisher."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from shipping_svc.adapters.outbound.carrier.acl import parse_time
from shipping_svc.adapters.outbound.persistence.models import ShipmentRow, TrackingEventRow
from shipping_svc.domain.model import Direction, Shipment, ShipmentStatus

_COLUMNS = (
    "order_id",
    "fulfilment_id",
    "return_id",
    "warehouse_id",
    "address",
    "parcel_count",
    "shipping_method",
    "carrier",
    "tracking_number",
    "booking_attempts",
    "next_attempt_at",
    "booked_at",
    "tracking_rank",
    "delivered_at",
    "correlation_id",
    "causation_id",
    "version",
)


def _claim_to_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": exp.isoformat() if isinstance(exp, datetime) else exp}


def _claim_from_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": datetime.fromisoformat(exp) if isinstance(exp, str) else exp}


def _shipment(r: ShipmentRow) -> Shipment:
    return Shipment(
        shipment_id=r.shipment_id,
        order_id=r.order_id,
        direction=Direction(r.direction),
        address=r.address,
        status=ShipmentStatus(r.status),
        correlation_id=r.correlation_id,
        fulfilment_id=r.fulfilment_id,
        return_id=r.return_id,
        warehouse_id=r.warehouse_id,
        parcel_count=r.parcel_count,
        shipping_method=r.shipping_method,
        carrier=r.carrier,
        tracking_number=r.tracking_number,
        label=_claim_from_json(r.label),
        booking_attempts=r.booking_attempts,
        next_attempt_at=r.next_attempt_at,
        booked_at=r.booked_at,
        tracking_rank=r.tracking_rank,
        delivered_at=r.delivered_at,
        causation_id=r.causation_id,
        version=r.version,
        created_at=r.created_at,
    )


class SqlShipmentRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def _one(self, cond: Any, for_update: bool) -> Shipment | None:
        q = select(ShipmentRow).where(cond)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        return _shipment(row) if row else None

    def get(self, shipment_id: str, *, for_update: bool = False) -> Shipment | None:
        return self._one(ShipmentRow.shipment_id == shipment_id, for_update)

    def by_fulfilment(self, fulfilment_id: str, *, for_update: bool = False) -> Shipment | None:
        return self._one(ShipmentRow.fulfilment_id == fulfilment_id, for_update)

    def by_return(self, return_id: str) -> Shipment | None:
        return self._one(ShipmentRow.return_id == return_id, False)

    def by_tracking_number(self, tracking_number: str, *, for_update: bool = False) -> Shipment | None:
        return self._one(ShipmentRow.tracking_number == tracking_number, for_update)

    def save(self, s: Shipment, now: datetime) -> None:
        values: dict[str, Any] = {c: getattr(s, c) for c in _COLUMNS}
        values.update(direction=s.direction.value, status=s.status.value, label=_claim_to_json(s.label))
        stmt = pg_insert(ShipmentRow).values(shipment_id=s.shipment_id, created_at=s.created_at or now, updated_at=now, **values)
        self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=["shipment_id"], set_={k: stmt.excluded[k] for k in [*values, "updated_at"]}
            )
        )

    def due_bookings(self, now: datetime, limit: int) -> list[Shipment]:
        rows = (
            self._s.execute(
                select(ShipmentRow)
                .where(ShipmentRow.status == ShipmentStatus.BOOKING_PENDING.value, ShipmentRow.next_attempt_at <= now)
                .order_by(ShipmentRow.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        return [_shipment(r) for r in rows]


class TrackingEventStore:
    """Raw carrier webhooks: written by the endpoint (store-then-ack), read by the processor."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def store(self, payload: dict[str, Any], now: datetime) -> None:
        self._s.execute(
            pg_insert(TrackingEventRow)
            .values(
                carrier_event_id=str(payload["carrierEventId"]),
                tracking_number=str(payload["trackingNumber"]),
                status=str(payload["status"]),
                exception_code=payload.get("exceptionCode"),
                location=payload.get("location"),
                occurred_at=parse_time(payload["occurredAt"]),
                payload=payload,
                received_at=now,
            )
            .on_conflict_do_nothing(index_elements=["carrier_event_id"])
        )

    def claim(self, limit: int) -> list[TrackingEventRow]:
        """Unprocessed rows in carrier-time order per arrival batch; SKIP LOCKED for parallel workers."""
        return list(
            self._s.execute(
                select(TrackingEventRow)
                .where(TrackingEventRow.processed_at.is_(None))
                .order_by(TrackingEventRow.received_at, TrackingEventRow.carrier_event_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars()
        )

    def mark(self, carrier_event_id: str, outcome: str, shipment_id: str | None, now: datetime) -> None:
        self._s.execute(
            update(TrackingEventRow)
            .where(TrackingEventRow.carrier_event_id == carrier_event_id)
            .values(processed_at=now, outcome=outcome, shipment_id=shipment_id)
        )

    def history(self, tracking_number: str) -> list[TrackingEventRow]:
        return list(
            self._s.execute(
                select(TrackingEventRow)
                .where(TrackingEventRow.tracking_number == tracking_number)
                .order_by(TrackingEventRow.occurred_at)
            ).scalars()
        )


class OutboxPublisher:
    """EventPublisher port on top of the shared OutboxWriter (same transaction)."""

    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
