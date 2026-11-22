"""Which fact deserves which message, and what it says. Pure: no I/O, no clock.

Each notice has a **dedupe key** = template + business id. The inbox already drops redelivered
events (same eventId); the dedupe key also drops a fact that a producer re-emitted with a new eventId
(a resent command answered with its original reply), so the customer gets one email per business
event (ADR-0006 applied to a side effect that cannot be undone).

Facts carry ids and amounts only. The recipient's name and address come from the contact store at
send time and are never put in a log line or an event (ADR-0013).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Notice:
    template: str
    business_id: str
    order_id: str
    facts: dict[str, str] = field(default_factory=dict)
    attachments: tuple[dict[str, Any], ...] = ()  # ClaimCheck (Avro shape), fetched and verified at send time

    @property
    def dedupe_key(self) -> str:
        return f"{self.template}:{self.business_id}"


@dataclass(frozen=True, slots=True)
class Rendered:
    subject: str
    text: str


def money(minor: int, currency: str) -> str:
    sign = "-" if minor < 0 else ""
    m = abs(minor)
    return f"{sign}{m // 100}.{m % 100:02d} {currency}"


_SUBJECTS = {
    "order-confirmed.v1": "Your order is confirmed",
    "order-cancelled.v1": "Your order was cancelled",
    "order-shipped.v1": "Your order is on its way",
    "invoice.v1": "Your invoice {invoiceNumber}",
    "order-delivered.v1": "Your order was delivered",
    "refund-issued.v1": "We refunded {amount}",
    "shipment-problem.v1": "A problem with your delivery",
    "return-label.v1": "Your return label",
    "return-authorized.v1": "Return {rmaNumber} approved",
    "return-rejected.v1": "Your return could not be accepted",
    "return-refunded.v1": "Refund of {amount} for your return",
    "return-expired.v1": "Your return has expired",
}

_BODIES = {
    "order-confirmed.v1": "We have your order {orderId} and the warehouse is preparing it.",
    "order-cancelled.v1": "Order {orderId} was cancelled ({reason}). {paymentNote}",
    "order-shipped.v1": "Order {orderId} has left the warehouse with {carrier}, tracking number {trackingNumber}.",
    "invoice.v1": "Attached is invoice {invoiceNumber} for order {orderId}, total {total}.",
    "order-delivered.v1": "Order {orderId} was delivered. You can return items until {returnWindowEndsAt}.",
    "refund-issued.v1": "We refunded {amount} for order {orderId}.",
    "shipment-problem.v1": "The carrier reported a problem with order {orderId}: {code}. We are on it.",
    "return-label.v1": "Attached is your return label, tracking number {trackingNumber}. Please drop the parcel off.",
    "return-authorized.v1": "Return {rmaNumber} for order {orderId} is approved. Please send it before {parcelDueBy}.",
    "return-rejected.v1": "Your return for order {orderId} could not be accepted: {reason}.",
    "return-refunded.v1": "We refunded {amount} for your return of order {orderId}.",
    "return-expired.v1": "We did not receive the parcel for your return of order {orderId} in time.",
}

TEMPLATES = frozenset(_SUBJECTS)


class _Safe(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def render(n: Notice, recipient_name: str | None) -> Rendered:
    if n.template not in TEMPLATES:
        raise ValueError(f"unknown template {n.template}")
    facts = _Safe({"orderId": n.order_id, **n.facts})
    greeting = f"Hello {recipient_name}," if recipient_name else "Hello,"
    return Rendered(_SUBJECTS[n.template].format_map(facts), f"{greeting}\n\n{_BODIES[n.template].format_map(facts)}\n")
