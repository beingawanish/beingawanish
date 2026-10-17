"""The trip state machine, as one table.

Every status change in the package goes through transition(). If an edge is
not in ALLOWED, the move is illegal and raises, with no partial update.
"""
from .errors import IllegalTransitionError
from .models import Trip, TripStatus

S = TripStatus

ALLOWED: dict[TripStatus, frozenset[TripStatus]] = {
    S.REQUESTED: frozenset({S.MATCHED, S.CANCELLED}),
    S.MATCHED: frozenset({S.DRIVER_ARRIVING, S.CANCELLED}),
    S.DRIVER_ARRIVING: frozenset({S.IN_PROGRESS, S.CANCELLED}),
    S.IN_PROGRESS: frozenset({S.COMPLETED}),
    S.COMPLETED: frozenset(),
    S.CANCELLED: frozenset(),
}


def can_transition(current: TripStatus, target: TripStatus) -> bool:
    return target in ALLOWED[current]


def transition(trip: Trip, target: TripStatus) -> None:
    """Move trip to target, or raise IllegalTransitionError and change nothing."""
    if not can_transition(trip.status, target):
        raise IllegalTransitionError(trip.trip_id, trip.status, target)
    trip.status = target
