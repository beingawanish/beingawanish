"""Shipping domain: carrier bookings and tracking normalisation (architecture §5.10). Pure.

Booking (one shipment per outbound fulfilment, one per return label)::

    BOOKING_PENDING --carrier booked--> BOOKED
          |  carrier unavailable: retry after 10 s, 1 min, 10 min, 1 h
          +--- 5 failed attempts ---> BOOKING_FAILED  (ShipmentException BOOKING_FAILED, a human looks)

A resent ``IssueReturnLabel`` for a ``BOOKING_FAILED`` return shipment starts the attempts again:
forward recovery, driven by the returns saga's own timeout.

Tracking: carriers send duplicates and send "delivered" before "in transit". Every raw update is
stored; only forward moves are emitted, each status at most once, so downstream services never see
a shipment move backwards::

    LABEL_CREATED=0  PICKED_UP=1  IN_TRANSIT=2  OUT_FOR_DELIVERY=3  DELIVERED=4      EXCEPTION: always

PICKED_UP, IN_TRANSIT and OUT_FOR_DELIVERY become ``ShipmentInTransit``; DELIVERED becomes
``ShipmentDelivered``; EXCEPTION becomes ``ShipmentException`` whenever seen (once per carrier event).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

BOOKING_BACKOFF = (timedelta(seconds=10), timedelta(minutes=1), timedelta(minutes=10), timedelta(hours=1))
MAX_BOOKING_ATTEMPTS = 5
LABEL_RETENTION = timedelta(days=30)  # bucket lifecycle rule (infra/minio/init.sh)


class Direction(StrEnum):
    OUTBOUND = "OUTBOUND"
    RETURN = "RETURN"


class ShipmentStatus(StrEnum):
    BOOKING_PENDING = "BOOKING_PENDING"
    BOOKED = "BOOKED"
    BOOKING_FAILED = "BOOKING_FAILED"


class CarrierStatus(StrEnum):
    LABEL_CREATED = "LABEL_CREATED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


RANK = {
    CarrierStatus.LABEL_CREATED: 0,
    CarrierStatus.PICKED_UP: 1,
    CarrierStatus.IN_TRANSIT: 2,
    CarrierStatus.OUT_FOR_DELIVERY: 3,
    CarrierStatus.DELIVERED: 4,
}
EXCEPTION_CODES = frozenset({"ADDRESS_ISSUE", "DAMAGED", "LOST", "DELAYED"})


@dataclass(frozen=True, slots=True)
class Shipment:
    shipment_id: str
    order_id: str
    direction: Direction
    address: dict[str, Any]
    status: ShipmentStatus
    correlation_id: str
    fulfilment_id: str | None = None
    return_id: str | None = None
    warehouse_id: str | None = None
    parcel_count: int = 1
    shipping_method: str = "STANDARD"
    carrier: str | None = None
    tracking_number: str | None = None
    label: dict[str, Any] | None = None  # ClaimCheck, Avro shape
    booking_attempts: int = 0
    next_attempt_at: datetime | None = None
    booked_at: datetime | None = None
    tracking_rank: int = 0
    delivered_at: datetime | None = None
    causation_id: str | None = None
    version: int = 0
    created_at: datetime | None = None

    def bump(self, **changes: Any) -> Shipment:
        return replace(self, version=self.version + 1, **changes)


@dataclass(frozen=True, slots=True)
class BookingFailure:
    """What to do after a failed booking attempt."""

    give_up: bool
    next_attempt_at: datetime | None


def after_failed_booking(attempts_so_far: int, now: datetime) -> BookingFailure:
    """``attempts_so_far`` includes the attempt that just failed."""
    if attempts_so_far >= MAX_BOOKING_ATTEMPTS:
        return BookingFailure(True, None)
    return BookingFailure(False, now + BOOKING_BACKOFF[min(attempts_so_far - 1, len(BOOKING_BACKOFF) - 1)])


class Emit(StrEnum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    EXCEPTION = "EXCEPTION"


@dataclass(frozen=True, slots=True)
class TrackingDecision:
    emit: Emit | None
    new_rank: int
    reason: str


def normalise(current_rank: int, status: CarrierStatus) -> TrackingDecision:
    """The carrier's vocabulary -> at most one forward-only event (webhooks.yaml CarrierTrackingEvent)."""
    if status is CarrierStatus.EXCEPTION:
        return TrackingDecision(Emit.EXCEPTION, current_rank, "exception: always emitted")
    rank = RANK[status]
    if rank <= current_rank:
        return TrackingDecision(None, current_rank, f"rank {rank} <= current {current_rank}: stored for history only")
    if status is CarrierStatus.DELIVERED:
        return TrackingDecision(Emit.DELIVERED, rank, "forward to delivered")
    if status is CarrierStatus.LABEL_CREATED:
        return TrackingDecision(None, rank, "label created: nothing to tell")
    return TrackingDecision(Emit.IN_TRANSIT, rank, f"forward to {status.value}")


def exception_code(raw: str | None) -> str:
    """Unknown carrier codes are passed on as UNKNOWN, never refused (guide §5 rule 9)."""
    return raw if raw in EXCEPTION_CODES else "UNKNOWN"
