"""Domain facts -> outgoing Avro messages (inventory.events.v1, inventory.stock-level.v1)."""

from __future__ import annotations

from datetime import datetime

from contracts_py.records import (
    ItemsRestocked,
    ReservationCommitted,
    ReservationExpired,
    ReservationReleased,
    StockLevelChanged,
    StockReservationRejected,
    StockReserved,
)
from edacommon.envelope import Causation, OutgoingMessage
from inventory_svc.domain.model import Reservation, StockLevel, StockLine

AGG = "Reservation"


def _lines(lines: tuple[StockLine, ...]) -> list[dict[str, object]]:
    return [{"sku": line.sku, "quantity": line.quantity} for line in lines]


def _msg(cls: type, res_order_id: str, aggregate_id: str, body: dict[str, object],
         causation: Causation | None = None) -> OutgoingMessage:
    return OutgoingMessage(topic=cls.TOPIC, record_type=cls.AVRO_NAME, key=res_order_id, body=body,  # type: ignore[attr-defined]
                           aggregate_type=AGG, aggregate_id=aggregate_id, causation=causation)


def stock_reserved(res: Reservation) -> OutgoingMessage:
    assert res.expires_at is not None
    return _msg(StockReserved, res.order_id, res.reservation_id, {
        "orderId": res.order_id, "reservationId": res.reservation_id, "lines": _lines(res.lines),
        "expiresAt": res.expires_at})


def stock_rejected(res: Reservation) -> OutgoingMessage:
    return _msg(StockReservationRejected, res.order_id, res.reservation_id, {
        "orderId": res.order_id, "reservationId": res.reservation_id,
        "shortages": [{"sku": s.sku, "requested": s.requested, "available": s.available} for s in res.shortages]})


def committed(res: Reservation, at: datetime) -> OutgoingMessage:
    return _msg(ReservationCommitted, res.order_id, res.reservation_id, {
        "orderId": res.order_id, "reservationId": res.reservation_id, "committedAt": at})


def released(order_id: str, reservation_id: str, reason: str, at: datetime) -> OutgoingMessage:
    return _msg(ReservationReleased, order_id, reservation_id, {
        "orderId": order_id, "reservationId": reservation_id, "reason": reason, "releasedAt": at})


def expired(res: Reservation, at: datetime, causation: Causation | None = None) -> OutgoingMessage:
    return _msg(ReservationExpired, res.order_id, res.reservation_id, {
        "orderId": res.order_id, "reservationId": res.reservation_id, "expiredAt": at}, causation)


def restocked(order_id: str, return_id: str, restock_id: str, lines: tuple[StockLine, ...], at: datetime) -> OutgoingMessage:
    return _msg(ItemsRestocked, order_id, restock_id, {
        "orderId": order_id, "returnId": return_id, "restockId": restock_id, "lines": _lines(lines),
        "restockedAt": at})


def stock_level(level: StockLevel, at: datetime, causation: Causation | None = None) -> OutgoingMessage:
    # Compacted topic keyed by sku: every record is a full snapshot (architecture §8.2).
    return OutgoingMessage(
        topic=StockLevelChanged.TOPIC, record_type=StockLevelChanged.AVRO_NAME, key=level.sku,
        aggregate_type="StockLevel", aggregate_id=level.sku, aggregate_version=level.version,
        causation=causation,
        body={"sku": level.sku, "onHand": level.on_hand, "reserved": level.reserved,
              "available": level.available, "asOf": at})
