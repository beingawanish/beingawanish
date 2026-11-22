"""The order-history projector (ADR-0010): a separate process from the same codebase, consumer group
``order-history-projector``, building ``order_history.*`` from six topics.

Monotonic reads: the summary row stores the ``aggregateVersion`` of the last *order* event applied;
an order event at or below it is dropped, so replays and reordering never move time backwards.
Events from other contexts carry their own aggregates' versions, so they only add timeline entries
(deduplicated by eventId) and side facts (refunds, shipment status, return status).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from contracts_py.topics import TOPIC_BY_NAME
from edacommon.consumer import HandlerRegistry
from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext
from edacommon.errors import RetryLater
from edacommon.logging import get_logger
from sqlalchemy import text
from sqlalchemy.orm import Session

log = get_logger(__name__)
GROUP = "order-history-projector"
TOPICS = [
    "order.events.v1",
    "payment.events.v1",
    "fulfilment.events.v1",
    "shipping.events.v1",
    "returns.events.v1",
    "notification.events.v1",
]

_ORDER_STATUS = {
    "OrderConfirmed": "CONFIRMED",
    "OrderCancelled": "CANCELLED",
    "OrderShipped": "SHIPPED",
    "OrderDelivered": "DELIVERED",
    "OrderRequiresAttention": "NEEDS_ATTENTION",
}
_SHIPMENT_STATUS = {
    "ShipmentCreated": "LABEL_CREATED",
    "ShipmentInTransit": "IN_TRANSIT",
    "ShipmentDelivered": "DELIVERED",
    "ShipmentException": "EXCEPTION",
}


def kind_of(record_type: str) -> str:
    name = record_type.rsplit(".", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).upper()


def _describe(name: str, v: dict[str, Any]) -> str | None:
    if name == "OrderCancelled":
        return f"Cancelled: {v.get('reason')}"
    if name == "OrderShipped":
        return f"Shipped with {v.get('carrier')} ({v.get('trackingNumber')})"
    if name == "InvoiceIssued":
        return f"Invoice {v.get('invoiceNumber')}"
    if name == "PaymentDeclined":
        return f"Payment declined: {v.get('reason')}"
    if name == "ShipmentInTransit" and v.get("location"):
        return f"In transit at {v.get('location')}"
    return None


class OrderHistoryProjection:
    def __init__(self, session: Session, schema: str = "order_history") -> None:
        self._s = session
        self._t = schema

    def _summary_version(self, order_id: str) -> int | None:
        v = self._s.execute(
            text(f"SELECT version FROM {self._t}.order_summary WHERE order_id = :o FOR UPDATE"), {"o": order_id}
        ).scalar_one_or_none()
        return None if v is None else int(v)

    def _timeline(self, order_id: str, event_id: str, at: datetime, kind: str, description: str | None) -> None:
        self._s.execute(
            text(
                f"INSERT INTO {self._t}.timeline (order_id, event_id, at, kind, description) VALUES (:o, :e, :a, :k, :d) "
                "ON CONFLICT DO NOTHING"
            ),
            {"o": order_id, "e": event_id, "a": at, "k": kind, "d": description},
        )

    def apply(self, record_type: str, value: dict[str, Any]) -> bool:
        """Apply one event. Returns False when it was stale and dropped."""
        env = value["envelope"]
        name = record_type.rsplit(".", 1)[-1]
        order_id = value.get("orderId")
        if not order_id:
            return False  # e.g. a notification without an order
        version = int(env.get("aggregateVersion") or 0)
        at = env["occurredAt"]
        current = self._summary_version(order_id)
        if record_type.startswith("com.edacommerce.order."):
            if current is not None and version <= current:
                return False
            if name == "OrderPlaced":
                self._place(value, version)
            else:
                if current is None:
                    raise RetryLater(f"{name} for {order_id} before OrderPlaced is projected")
                self._order_event(name, value, version)
        else:
            if current is None:
                raise RetryLater(f"{name} for {order_id} before OrderPlaced is projected")
            self._side_fact(name, value)
        self._timeline(order_id, env["eventId"], at, kind_of(record_type), _describe(name, value))
        return True

    def _place(self, v: dict[str, Any], version: int) -> None:
        lines = v["lines"]
        self._s.execute(
            text(
                f"INSERT INTO {self._t}.order_summary (order_id, customer_id, status, total_minor, currency, item_count, "
                "placed_at, version) VALUES (:o, :c, 'PENDING', :t, :cur, :n, :p, :v) "
                "ON CONFLICT (order_id) DO UPDATE SET version = EXCLUDED.version"
            ),
            {
                "o": v["orderId"],
                "c": v["customerId"],
                "t": v["total"]["amountMinor"],
                "cur": v["total"]["currency"],
                "n": sum(int(x["quantity"]) for x in lines),
                "p": v["placedAt"],
                "v": version,
            },
        )
        for i, x in enumerate(lines):
            self._s.execute(
                text(
                    f"INSERT INTO {self._t}.order_line (order_id, line_id, position, sku, product_name, quantity, "
                    "unit_price_minor, line_total_minor) VALUES (:o, :l, :i, :s, :pn, :q, :u, :lt) ON CONFLICT DO NOTHING"
                ),
                {
                    "o": v["orderId"],
                    "l": x["lineId"],
                    "i": i,
                    "s": x["sku"],
                    "pn": x["productName"],
                    "q": x["quantity"],
                    "u": x["unitPrice"]["amountMinor"],
                    "lt": x["lineTotal"]["amountMinor"],
                },
            )

    def _order_event(self, name: str, v: dict[str, Any], version: int) -> None:
        sets = ["version = :v"]
        params: dict[str, Any] = {"o": v["orderId"], "v": version}
        if name in _ORDER_STATUS:
            sets.append("status = :st")
            params["st"] = _ORDER_STATUS[name]
        if name == "OrderCancelled":
            sets.append("cancellation_reason = :r")
            params["r"] = v["reason"]
        if name == "OrderShipped":
            sets += ["carrier = :ca", "tracking_number = :tn"]
            params.update(ca=v["carrier"], tn=v["trackingNumber"])
        if name == "OrderDelivered":
            sets.append("shipment_status = 'DELIVERED'")
        if name == "InvoiceIssued":
            sets.append("invoice_available = true")
        self._s.execute(text(f"UPDATE {self._t}.order_summary SET {', '.join(sets)} WHERE order_id = :o"), params)

    def _side_fact(self, name: str, v: dict[str, Any]) -> None:
        o = v["orderId"]
        if name == "RefundSucceeded":
            self._s.execute(
                text(f"UPDATE {self._t}.order_summary SET refunded_minor = refunded_minor + :a WHERE order_id = :o"),
                {"a": v["amount"]["amountMinor"], "o": o},
            )
        elif name in _SHIPMENT_STATUS and v.get("direction") == "OUTBOUND":
            self._s.execute(
                text(f"UPDATE {self._t}.order_summary SET shipment_status = :s WHERE order_id = :o"),
                {"s": _SHIPMENT_STATUS[name], "o": o},
            )
        elif name == "ReturnRequested":
            self._s.execute(
                text(f"UPDATE {self._t}.order_summary SET status = 'RETURN_IN_PROGRESS' WHERE order_id = :o"), {"o": o}
            )
        elif name == "ReturnClosed":
            status = {"REFUNDED": "RETURNED", "PARTIALLY_REFUNDED": "PARTIALLY_RETURNED"}.get(v.get("outcome", ""), "DELIVERED")
            self._s.execute(text(f"UPDATE {self._t}.order_summary SET status = :s WHERE order_id = :o"), {"s": status, "o": o})


def build_registry(schema: str = "order_history") -> HandlerRegistry:
    """One raw handler per message type on the six topics (reader schema = the bundled one)."""
    reg = HandlerRegistry()

    def handle(value: dict[str, Any], ctx: MessageContext, uow: UnitOfWork) -> None:
        if not OrderHistoryProjection(uow.session, schema).apply(ctx.event_type, value):
            log.info("stale or irrelevant event dropped", event_type=ctx.event_type)

    from contracts_py.records import MESSAGE_TYPES

    for topic in TOPICS:
        for full in TOPIC_BY_NAME[topic].messages:
            reg.register(MESSAGE_TYPES[full], handle, raw=True)
    return reg
