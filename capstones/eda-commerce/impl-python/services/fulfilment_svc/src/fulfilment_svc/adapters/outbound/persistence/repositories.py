"""Postgres implementation of :class:`FulfilmentRepository` and the outbox-backed EventPublisher."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from edacommon.envelope import OutgoingMessage
from edacommon.outbox import OutboxWriter
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from fulfilment_svc.adapters.outbound.persistence.models import FulfilmentRow, ParcelRow, ReturnIntakeRow
from fulfilment_svc.domain.model import (
    Fulfilment,
    FulfilmentStatus,
    InspectionOutcome,
    InspectionResult,
    IntakeStatus,
    OrderLine,
    Parcel,
    ReturnIntake,
    ReturnLine,
)

_F_COLUMNS = (
    "order_id",
    "status",
    "lines",
    "ship_to",
    "shipping_method",
    "attempt",
    "wms_submissions",
    "warehouse_id",
    "accepted_at",
    "estimated_dispatch_at",
    "picked_at",
    "packed_at",
    "dispatched_at",
    "cancelled_at",
    "failed_at",
    "failure_reason",
    "failure_detail",
    "manifest",
    "shipment_id",
    "last_command_id",
    "correlation_id",
    "version",
)


def _claim_to_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    """ClaimCheck (Avro shape, datetimes) -> JSONB; and back."""
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": exp.isoformat() if isinstance(exp, datetime) else exp}


def _claim_from_json(cc: dict[str, Any] | None) -> dict[str, Any] | None:
    if cc is None:
        return None
    exp = cc.get("expiresAt")
    return {**cc, "expiresAt": datetime.fromisoformat(exp) if isinstance(exp, str) else exp}


def _upsert(session: Session, model: Any, key: str, values: dict[str, Any], now: datetime) -> None:
    stmt = pg_insert(model).values(created_at=now, updated_at=now, **values)
    session.execute(
        stmt.on_conflict_do_update(index_elements=[key], set_={k: stmt.excluded[k] for k in [*values, "updated_at"] if k != key})
    )


class SqlFulfilmentRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ---------------------------------------------------------------------------- fulfilment
    def get(self, fulfilment_id: str, *, for_update: bool = False) -> Fulfilment | None:
        q = select(FulfilmentRow).where(FulfilmentRow.fulfilment_id == fulfilment_id)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        if row is None:
            return None
        parcels = self._s.execute(
            select(ParcelRow).where(ParcelRow.fulfilment_id == fulfilment_id).order_by(ParcelRow.parcel_id)
        ).scalars()
        return Fulfilment(
            fulfilment_id=row.fulfilment_id,
            order_id=row.order_id,
            status=FulfilmentStatus(row.status),
            lines=tuple(OrderLine(**x) for x in row.lines),
            ship_to=row.ship_to,
            shipping_method=row.shipping_method,
            correlation_id=row.correlation_id,
            attempt=row.attempt,
            wms_submissions=row.wms_submissions,
            warehouse_id=row.warehouse_id,
            accepted_at=row.accepted_at,
            estimated_dispatch_at=row.estimated_dispatch_at,
            picked_at=row.picked_at,
            packed_at=row.packed_at,
            dispatched_at=row.dispatched_at,
            cancelled_at=row.cancelled_at,
            failed_at=row.failed_at,
            failure_reason=row.failure_reason,
            failure_detail=row.failure_detail,
            manifest=_claim_from_json(row.manifest),
            parcels=tuple(Parcel(p.parcel_id, p.weight_grams, p.length_mm, p.width_mm, p.height_mm) for p in parcels),
            shipment_id=row.shipment_id,
            last_command_id=row.last_command_id,
            version=row.version,
            created_at=row.created_at,
        )

    def save(self, f: Fulfilment, now: datetime) -> None:
        values: dict[str, Any] = {c: getattr(f, c) for c in _F_COLUMNS}
        values["status"] = f.status.value
        values["manifest"] = _claim_to_json(f.manifest)
        values["lines"] = [
            {"line_id": x.line_id, "sku": x.sku, "product_name": x.product_name, "quantity": x.quantity} for x in f.lines
        ]
        _upsert(self._s, FulfilmentRow, "fulfilment_id", {"fulfilment_id": f.fulfilment_id, **values}, now)
        if f.parcels:
            self._s.execute(
                pg_insert(ParcelRow)
                .values(
                    [
                        {
                            "parcel_id": p.parcel_id,
                            "fulfilment_id": f.fulfilment_id,
                            "weight_grams": p.weight_grams,
                            "length_mm": p.length_mm,
                            "width_mm": p.width_mm,
                            "height_mm": p.height_mm,
                        }
                        for p in f.parcels
                    ]
                )
                .on_conflict_do_nothing(index_elements=["parcel_id"])
            )

    # -------------------------------------------------------------------------- return intake
    def get_intake(self, return_id: str, *, for_update: bool = False) -> ReturnIntake | None:
        q = select(ReturnIntakeRow).where(ReturnIntakeRow.return_id == return_id)
        if for_update:
            q = q.with_for_update()
        row = self._s.execute(q).scalar_one_or_none()
        if row is None:
            return None
        return ReturnIntake(
            return_id=row.return_id,
            order_id=row.order_id,
            rma_number=row.rma_number,
            status=IntakeStatus(row.status),
            lines=tuple(ReturnLine(**x) for x in row.lines),
            expected_by=row.expected_by,
            correlation_id=row.correlation_id,
            shipment_id=row.shipment_id,
            received_at=row.received_at,
            received_event_id=row.received_event_id,
            results=tuple(
                InspectionResult(x["line_id"], x["sku"], int(x["quantity"]), InspectionOutcome(x["outcome"]), x.get("note"))
                for x in (row.results or [])
            ),
            inspected_at=row.inspected_at,
            version=row.version,
        )

    def save_intake(self, r: ReturnIntake, now: datetime) -> None:
        values: dict[str, Any] = {
            "return_id": r.return_id,
            "order_id": r.order_id,
            "rma_number": r.rma_number,
            "status": r.status.value,
            "lines": [{"line_id": x.line_id, "sku": x.sku, "quantity": x.quantity} for x in r.lines],
            "expected_by": r.expected_by,
            "shipment_id": r.shipment_id,
            "received_at": r.received_at,
            "received_event_id": r.received_event_id,
            "results": [
                {"line_id": x.line_id, "sku": x.sku, "quantity": x.quantity, "outcome": x.outcome.value, "note": x.note}
                for x in r.results
            ]
            if r.results
            else None,
            "inspected_at": r.inspected_at,
            "correlation_id": r.correlation_id,
            "version": r.version,
        }
        _upsert(self._s, ReturnIntakeRow, "return_id", values, now)

    def delete_all(self) -> None:  # tests only
        for model in (ParcelRow, ReturnIntakeRow, FulfilmentRow):
            self._s.execute(delete(model))


class OutboxPublisher:
    """EventPublisher port on top of the shared OutboxWriter (same transaction)."""

    def __init__(self, session: Session, writer: OutboxWriter) -> None:
        self._s = session
        self._w = writer

    def publish(self, msg: OutgoingMessage) -> None:
        self._w.append(self._s, msg)
