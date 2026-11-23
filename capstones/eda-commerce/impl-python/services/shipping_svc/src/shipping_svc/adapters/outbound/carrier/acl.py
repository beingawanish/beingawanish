"""Anti-corruption layer: carrier webhook JSON (webhooks.yaml ``CarrierTrackingEvent``) -> domain.

The only code that knows the carrier's field names. A real carrier adapter brings its own mapping.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shipping_svc.application.ports import TrackingUpdate
from shipping_svc.domain.model import CarrierStatus

REQUIRED = ("carrierEventId", "trackingNumber", "status", "occurredAt")


def validate(payload: dict[str, Any]) -> str:
    """Raise ValueError/KeyError for an unparseable webhook (-> 400); return its status."""
    for k in REQUIRED:
        if not payload.get(k):
            raise KeyError(k)
    CarrierStatus(payload["status"])  # unknown vocabulary is a 400, the carrier will not retry it
    parse_time(payload["occurredAt"])
    return str(payload["status"])


def parse_time(v: str) -> datetime:
    dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("occurredAt must carry a time zone")
    return dt


def to_update(payload: dict[str, Any], received_at: datetime) -> TrackingUpdate:
    return TrackingUpdate(
        carrier_event_id=str(payload["carrierEventId"]),
        tracking_number=str(payload["trackingNumber"]),
        status=CarrierStatus(payload["status"]),
        occurred_at=parse_time(payload["occurredAt"]),
        received_at=received_at,
        exception_code=payload.get("exceptionCode"),
        location=payload.get("location"),
    )
