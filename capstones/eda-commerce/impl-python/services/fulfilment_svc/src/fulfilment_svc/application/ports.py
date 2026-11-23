"""Ports of fulfilment-svc. The warehouse port is implemented by the fake WMS today and by a real WMS
client tomorrow (architecture §2: anti-corruption layer); the domain never sees WMS formats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from edacommon.envelope import OutgoingMessage

from fulfilment_svc.domain.model import (
    Fulfilment,
    InspectionResult,
    OrderLine,
    Parcel,
    ReturnIntake,
    ReturnLine,
    WarehouseStep,
)


# ------------------------------------------------------------------------------------ warehouse
@dataclass(frozen=True, slots=True)
class WarehouseEvent:
    """Progress reported by the warehouse. ``event_id`` lets the pump acknowledge it after commit."""

    event_id: str
    fulfilment_id: str
    step: WarehouseStep
    at: datetime
    warehouse_id: str | None = None
    estimated_dispatch_at: datetime | None = None
    parcels: tuple[Parcel, ...] = ()
    manifest: bytes | None = None  # packing manifest (per-item scans, lots, serials), large on purpose
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True, slots=True)
class InspectionReport:
    event_id: str
    return_id: str
    at: datetime
    results: tuple[InspectionResult, ...]


class Warehouse(Protocol):
    """Asynchronous like a real WMS: requests are fire-and-forget (and may be lost), progress arrives
    later through :meth:`poll`. A real adapter would receive callbacks or read a WMS queue instead."""

    def submit_pick_order(self, *, fulfilment_id: str, order_id: str, lines: tuple[OrderLine, ...], now: datetime) -> None: ...

    def cancel_pick_order(self, fulfilment_id: str) -> None: ...

    def inspect_return(self, *, return_id: str, lines: tuple[ReturnLine, ...], now: datetime) -> None: ...

    def poll(self, now: datetime) -> list[WarehouseEvent | InspectionReport]: ...

    def ack(self, event_id: str) -> None: ...


# ---------------------------------------------------------------------------------- persistence
class FulfilmentRepository(Protocol):
    def get(self, fulfilment_id: str, *, for_update: bool = False) -> Fulfilment | None: ...

    def save(self, f: Fulfilment, now: datetime) -> None: ...

    def get_intake(self, return_id: str, *, for_update: bool = False) -> ReturnIntake | None: ...

    def save_intake(self, r: ReturnIntake, now: datetime) -> None: ...


class ManifestStore(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str, expires_at: datetime) -> dict[str, Any]:
        """Upload (object first, event second, ADR-0009) and return the ClaimCheck in Avro shape."""
        ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...
