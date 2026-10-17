"""Car rental domain: fleet, reservations, pricing."""
from .clock import Clock, FixedClock, SystemClock
from .config import AddOnRates, RentalConfig, VehicleCategory
from .errors import (
    AlreadyCancelledError,
    DuplicateVehicleError,
    InvalidDateRangeError,
    RentalError,
    ReservationConflictError,
    ReservationInPastError,
    ReservationNotFoundError,
    VehicleNotFoundError,
)
from .factory import ReservationFactory
from .models import AddOns, Reservation, Vehicle
from .pricing import PricingStrategy, StandardPricing
from .repositories import (
    FleetRepository,
    InMemoryFleet,
    InMemoryReservations,
    ReservationRepository,
)
from .service import RentalService

__all__ = [
    "AddOns", "Reservation", "Vehicle",
    "VehicleCategory", "RentalConfig", "AddOnRates",
    "Clock", "SystemClock", "FixedClock",
    "FleetRepository", "InMemoryFleet",
    "ReservationRepository", "InMemoryReservations",
    "PricingStrategy", "StandardPricing",
    "ReservationFactory", "RentalService",
    "RentalError", "VehicleNotFoundError", "DuplicateVehicleError",
    "ReservationNotFoundError", "InvalidDateRangeError",
    "ReservationInPastError", "ReservationConflictError",
    "AlreadyCancelledError",
]
