"""Domain errors for movie ticket booking.

One base class, so a caller can catch "any booking failure" in one clause,
and one subclass per failure mode, so it can also catch exactly one.
"""


class BookingError(Exception):
    """Base class for every movie-booking failure."""


class InvalidConfigError(BookingError, ValueError):
    """A BookingConfig value is out of range."""


class InvalidRequestError(BookingError, ValueError):
    """A public method received input it must reject at the door."""


class InvalidSeatSelectionError(InvalidRequestError):
    """Empty, duplicated, unknown, or too many seats."""


class NotFoundError(BookingError, LookupError):
    """An id that does not exist in a repository."""


class ShowNotFoundError(NotFoundError):
    pass


class BookingNotFoundError(NotFoundError):
    pass


class SeatUnavailableError(BookingError):
    """Someone else holds or owns at least one of the requested seats."""

    def __init__(self, show_id: str, seat_ids: list[str]) -> None:
        self.show_id = show_id
        self.seat_ids = seat_ids
        super().__init__(f"show {show_id}: seats not available: {', '.join(seat_ids)}")


class HoldExpiredError(BookingError):
    """The seat hold ran out before the booking was confirmed."""


class InvalidTransitionError(BookingError):
    """The booking state machine does not allow this move."""


class ShowClosedError(BookingError):
    """The show has started: no new holds, no cancellations."""


class IdempotencyConflictError(BookingError):
    """An idempotency key was reused for a different request."""


class PaymentError(BookingError):
    """The payment gateway could not complete a charge or refund."""


class PaymentDeclinedError(PaymentError):
    """The gateway refused the charge. Nothing was taken."""
