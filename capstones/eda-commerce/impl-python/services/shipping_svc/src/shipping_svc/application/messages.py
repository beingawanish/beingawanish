"""Domain facts -> outgoing Avro messages on shipping.events.v1 (key = orderId)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from contracts_py.records import ShipmentCreated, ShipmentDelivered, ShipmentException, ShipmentInTransit
from edacommon.envelope import Causation, OutgoingMessage

from shipping_svc.domain.model import Shipment

AGG = "Shipment"


def _msg(cls: Any, s: Shipment, body: dict[str, Any], causation: Causation | None) -> OutgoingMessage:
    return OutgoingMessage(
        topic=cls.TOPIC,
        record_type=cls.AVRO_NAME,
        key=s.order_id,
        body={"orderId": s.order_id, "shipmentId": s.shipment_id, "direction": s.direction.value, **body},
        aggregate_type=AGG,
        aggregate_id=s.shipment_id,
        aggregate_version=s.version,
        causation=causation,
    )


def created(s: Shipment, causation: Causation | None = None) -> OutgoingMessage:
    assert s.carrier
    assert s.tracking_number
    assert s.label
    assert s.booked_at
    return _msg(
        ShipmentCreated,
        s,
        {
            "carrier": s.carrier,
            "trackingNumber": s.tracking_number,
            "label": s.label,
            "createdAt": s.booked_at,
            "fulfilmentId": s.fulfilment_id,
            "returnId": s.return_id,
        },
        causation,
    )


def in_transit(s: Shipment, carrier_event_id: str, at: datetime, location: str | None, causation: Causation) -> OutgoingMessage:
    return _msg(
        ShipmentInTransit, s, {"carrierEventId": carrier_event_id, "carrierTimestamp": at, "location": location}, causation
    )


def delivered(s: Shipment, carrier_event_id: str, at: datetime, causation: Causation) -> OutgoingMessage:
    return _msg(ShipmentDelivered, s, {"carrierEventId": carrier_event_id, "deliveredAt": at, "returnId": s.return_id}, causation)


def exception(
    s: Shipment, code: str, at: datetime, detail: str | None, carrier_event_id: str | None, causation: Causation | None
) -> OutgoingMessage:
    return _msg(
        ShipmentException,
        s,
        {"code": code, "raisedAt": at, "detail": detail, "carrierEventId": carrier_event_id},
        causation,
    )
