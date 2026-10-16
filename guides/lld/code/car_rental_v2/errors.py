"""Version 2 errors. Every one extends v1's RentalError, so a caller that
already catches RentalError keeps working when v2 code raises."""
from car_rental import RentalError


class InvalidTransitionError(RentalError):
    """The vehicle state machine does not allow this move."""


class VehicleNotReadyError(RentalError):
    """The car cannot be handed out: wrong state, wrong branch, low charge."""


class UnknownBranchError(RentalError):
    pass


class BranchMismatchError(RentalError):
    """The car will not be where the trip needs it, or the trip strands a later one."""


class TripNotFoundError(RentalError):
    pass


class RentalStageError(RentalError):
    """The use case does not fit the trip's stage (inspect before return, ...)."""


class PaymentError(RentalError):
    """Base for money problems."""


class GatewayTimeoutError(PaymentError):
    """The gateway did not answer. The operation may or may not have happened."""


class IdempotencyConflictError(PaymentError):
    """An idempotency key was reused for a different request."""


class PaymentStateError(PaymentError):
    """Capture beyond the hold, capture after release, settle with no hold."""
