"""Domain errors for car rental."""


class RentalError(Exception):
    """Base of every error the rental domain can raise."""


class VehicleNotFoundError(RentalError):
    pass


class DuplicateVehicleError(RentalError):
    pass


class ReservationNotFoundError(RentalError):
    pass


class InvalidDateRangeError(RentalError):
    pass


class ReservationInPastError(RentalError):
    pass


class ReservationConflictError(RentalError):
    """A vehicle is already booked for part of the requested window."""


class AlreadyCancelledError(RentalError):
    pass
