"""The order lifecycle as data: statuses, actors, and the legal moves.

The transition table is the whole state machine. Order.advance() consults it
and nothing else, so adding a status is an edit to this table, not a hunt
through if-statements scattered across the service.
"""
from enum import Enum


class OrderStatus(Enum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    PICKED_UP = "picked_up"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Actor(Enum):
    """Who asked for a change. Refund rules depend on it."""
    CUSTOMER = "customer"
    RESTAURANT = "restaurant"
    PARTNER = "partner"
    PLATFORM = "platform"


TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PLACED: frozenset({OrderStatus.ACCEPTED, OrderStatus.REJECTED,
                                   OrderStatus.CANCELLED}),
    OrderStatus.ACCEPTED: frozenset({OrderStatus.PREPARING, OrderStatus.CANCELLED}),
    OrderStatus.PREPARING: frozenset({OrderStatus.READY, OrderStatus.CANCELLED}),
    OrderStatus.READY: frozenset({OrderStatus.PICKED_UP, OrderStatus.CANCELLED}),
    OrderStatus.PICKED_UP: frozenset({OrderStatus.DELIVERED}),
    OrderStatus.DELIVERED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
}

TERMINAL: frozenset[OrderStatus] = frozenset(
    status for status, targets in TRANSITIONS.items() if not targets)


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    return target in TRANSITIONS[current]
