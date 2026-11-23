"""Domain facts -> outgoing Avro messages on fulfilment.events.v1 (key = orderId).

``aggregateVersion`` is the row version of the fulfilment (or return intake) after the change, so
read models can drop stale updates.
"""

from __future__ import annotations

from typing import Any

from contracts_py.records import (
    FulfilmentAccepted,
    FulfilmentCancelled,
    FulfilmentFailed,
    OrderDispatched,
    OrderPacked,
    OrderPicked,
    ReturnInspected,
    ReturnReceived,
)
from edacommon.envelope import Causation, OutgoingMessage

from fulfilment_svc.domain.model import Fulfilment, ReturnIntake

AGG = "Fulfilment"


def _msg(
    cls: Any, key: str, aggregate_id: str, version: int, body: dict[str, Any], causation: Causation | None
) -> OutgoingMessage:
    return OutgoingMessage(
        topic=cls.TOPIC,
        record_type=cls.AVRO_NAME,
        key=key,
        body=body,
        aggregate_type=AGG,
        aggregate_id=aggregate_id,
        aggregate_version=version,
        causation=causation,
    )


def _f(cls: Any, f: Fulfilment, body: dict[str, Any], causation: Causation | None) -> OutgoingMessage:
    return _msg(
        cls, f.order_id, f.fulfilment_id, f.version, {"orderId": f.order_id, "fulfilmentId": f.fulfilment_id, **body}, causation
    )


def accepted(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.warehouse_id
    assert f.accepted_at
    return _f(
        FulfilmentAccepted,
        f,
        {"warehouseId": f.warehouse_id, "acceptedAt": f.accepted_at, "estimatedDispatchAt": f.estimated_dispatch_at},
        causation,
    )


def picked(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.picked_at
    return _f(OrderPicked, f, {"pickedAt": f.picked_at}, causation)


def packed(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.manifest
    assert f.packed_at
    assert f.warehouse_id
    assert f.ship_to is not None
    return _f(
        OrderPacked,
        f,
        {
            "warehouseId": f.warehouse_id,
            "parcels": [
                {
                    "parcelId": p.parcel_id,
                    "weightGrams": p.weight_grams,
                    "lengthMm": p.length_mm,
                    "widthMm": p.width_mm,
                    "heightMm": p.height_mm,
                }
                for p in f.parcels
            ],
            "manifest": f.manifest,
            "shipTo": f.ship_to,
            "shippingMethod": f.shipping_method,
            "packedAt": f.packed_at,
        },
        causation,
    )


def dispatched(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.shipment_id
    assert f.dispatched_at
    return _f(OrderDispatched, f, {"shipmentId": f.shipment_id, "dispatchedAt": f.dispatched_at}, causation)


def cancelled(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.cancelled_at
    return _f(FulfilmentCancelled, f, {"cancelledAt": f.cancelled_at}, causation)


def failed(f: Fulfilment, causation: Causation | None = None) -> OutgoingMessage:
    assert f.failed_at
    assert f.failure_reason
    return _f(FulfilmentFailed, f, {"reason": f.failure_reason, "failedAt": f.failed_at, "detail": f.failure_detail}, causation)


def return_received(r: ReturnIntake, causation: Causation | None = None) -> OutgoingMessage:
    assert r.received_at
    return _msg(
        ReturnReceived,
        r.order_id,
        r.return_id,
        r.version,
        {"orderId": r.order_id, "returnId": r.return_id, "receivedAt": r.received_at},
        causation,
    )


def return_inspected(r: ReturnIntake, causation: Causation | None = None) -> OutgoingMessage:
    assert r.inspected_at
    return _msg(
        ReturnInspected,
        r.order_id,
        r.return_id,
        r.version,
        {
            "orderId": r.order_id,
            "returnId": r.return_id,
            "results": [
                {"lineId": x.line_id, "sku": x.sku, "quantity": x.quantity, "outcome": x.outcome.value, "note": x.note}
                for x in r.results
            ],
            "inspectedAt": r.inspected_at,
        },
        causation,
    )
