"""Every way a ride-sharing operation can fail, as one typed hierarchy.

Callers catch exactly the failure they can handle: a rider app shows
"no drivers nearby" for one type and "that offer has expired" for another.
"""


class RideSharingError(Exception):
    """Base class for every domain failure in this package."""


class InvalidInputError(RideSharingError, ValueError):
    """A caller passed a value that can never be valid (blank id, bad config)."""


class NotFoundError(RideSharingError, LookupError):
    """Base for unknown ids."""


class RiderNotFoundError(NotFoundError):
    pass


class DriverNotFoundError(NotFoundError):
    pass


class TripNotFoundError(NotFoundError):
    pass


class OfferNotFoundError(NotFoundError):
    """The offer was never made, or it was already answered or withdrawn."""


class DuplicateIdError(RideSharingError):
    pass


class IllegalTransitionError(RideSharingError):
    """The trip state machine refused a move, e.g. COMPLETED -> IN_PROGRESS."""

    def __init__(self, trip_id: str, current: object, target: object) -> None:
        super().__init__(f"trip {trip_id}: cannot go from {current} to {target}")
        self.trip_id = trip_id
        self.current = current
        self.target = target


class DriverBusyError(RideSharingError):
    """The driver holds an offer or a trip and cannot change status now."""


class OfferExpiredError(RideSharingError):
    """The driver answered after the offer deadline; the trip moved on."""


class RatingError(RideSharingError):
    """A rating was out of range, too early, or a duplicate."""
