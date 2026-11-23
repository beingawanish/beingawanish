"""Ports of shipping-svc. The carrier port is implemented by the fake carrier today and by a real
carrier client tomorrow; the domain never sees carrier status strings (anti-corruption layer)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from edacommon.envelope import OutgoingMessage

from shipping_svc.domain.model import CarrierStatus, Direction, Shipment


class CarrierUnavailable(Exception):
    """The carrier's booking API refused or did not answer. Retried on the booking schedule."""


@dataclass(frozen=True, slots=True)
class Booking:
    carrier: str
    tracking_number: str


class Carrier(Protocol):
    def book(self, *, shipment_id: str, direction: Direction, address: dict[str, Any], parcel_count: int) -> Booking:
        """Idempotent on ``shipment_id``: booking twice returns the same tracking number."""
        ...


@dataclass(frozen=True, slots=True)
class LabelData:
    shipment_id: str
    order_id: str
    direction: Direction
    carrier: str
    tracking_number: str
    address: dict[str, Any]
    parcel_count: int
    shipping_method: str
    booked_at: datetime


class LabelRenderer(Protocol):
    def render(self, label: LabelData) -> bytes: ...


class LabelStore(Protocol):
    def put(self, bucket: str, key: str, data: bytes, content_type: str, expires_at: datetime) -> dict[str, Any]:
        """Upload (object first, event second, ADR-0009) and return the ClaimCheck in Avro shape."""
        ...


@dataclass(frozen=True, slots=True)
class TrackingUpdate:
    """One stored carrier webhook, already translated from carrier JSON by the inbound adapter."""

    carrier_event_id: str
    tracking_number: str
    status: CarrierStatus
    occurred_at: datetime
    received_at: datetime
    exception_code: str | None = None
    location: str | None = None


class ShipmentRepository(Protocol):
    def get(self, shipment_id: str, *, for_update: bool = False) -> Shipment | None: ...

    def by_fulfilment(self, fulfilment_id: str, *, for_update: bool = False) -> Shipment | None: ...

    def by_tracking_number(self, tracking_number: str, *, for_update: bool = False) -> Shipment | None: ...

    def save(self, s: Shipment, now: datetime) -> None: ...

    def due_bookings(self, now: datetime, limit: int) -> list[Shipment]: ...


class EventPublisher(Protocol):
    def publish(self, msg: OutgoingMessage) -> None: ...
