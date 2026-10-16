"""The use-case layer: search, reserve, cancel, return, quote.

The service orchestrates; it does not validate dates (the factory does),
does not compute prices (the strategy does), and does not store anything
(the repositories do). One RLock makes reserve-then-check atomic, so two
threads cannot book the same window.
"""
import logging
import threading
from datetime import date

from .clock import Clock, SystemClock
from .config import RentalConfig, VehicleCategory
from .errors import (
    AlreadyCancelledError,
    DuplicateVehicleError,
    InvalidDateRangeError,
    RentalError,
    ReservationConflictError,
    ReservationNotFoundError,
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

log = logging.getLogger(__name__)


def _require_text(value: str, name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value.strip()


class RentalService:
    def __init__(
        self,
        *,
        fleet: FleetRepository | None = None,
        reservations: ReservationRepository | None = None,
        pricing: PricingStrategy | None = None,
        factory: ReservationFactory | None = None,
        clock: Clock | None = None,
        config: RentalConfig | None = None,
    ):
        self._config = config or RentalConfig()
        self._fleet = fleet or InMemoryFleet()
        self._reservations = reservations or InMemoryReservations()
        self._clock = clock or SystemClock()
        self._pricing = pricing or StandardPricing()
        self._factory = factory or ReservationFactory(self._fleet, self._clock)
        self._lock = threading.RLock()

    # -- fleet ----------------------------------------------------------

    def add_vehicle(self, vehicle_id: str, category: VehicleCategory,
                    make: str, model: str, year: int) -> Vehicle:
        vehicle_id = _require_text(vehicle_id, "vehicle_id")
        if not isinstance(category, VehicleCategory):
            raise ValueError("category must be a VehicleCategory")
        if self._fleet.get(vehicle_id) is not None:
            raise DuplicateVehicleError(f"vehicle {vehicle_id} already exists")
        vehicle = Vehicle(vehicle_id=vehicle_id, category=category,
                          make=_require_text(make, "make"),
                          model=_require_text(model, "model"), year=year)
        self._fleet.add(vehicle)
        log.info("added vehicle %s (%s %s)", vehicle_id, make, model)
        return vehicle

    # -- booking --------------------------------------------------------

    def search_available(self, category: VehicleCategory,
                         start: date, end: date) -> list[Vehicle]:
        self._check_range(start, end)
        return [v for v in self._fleet.by_category(category)
                if not self._reservations.has_overlap(v.vehicle_id, start, end)]

    def reserve(self, vehicle_id: str, customer_name: str,
                start: date, end: date, add_ons: AddOns | None = None) -> Reservation:
        with self._lock:
            reservation = self._factory.create(
                vehicle_id, customer_name, start, end, add_ons)
            if self._reservations.has_overlap(vehicle_id, start, end):
                raise ReservationConflictError(
                    f"{vehicle_id} is already booked for part of "
                    f"{start}..{end}")
            self._reservations.add(reservation)
            log.info("reserved %s: %s %s..%s",
                     reservation.reservation_id, vehicle_id, start, end)
            return reservation

    def cancel(self, reservation_id: str) -> None:
        with self._lock:
            reservation = self._reservations.get(reservation_id)
            if reservation is None:
                raise ReservationNotFoundError(f"no reservation {reservation_id}")
            if reservation.cancelled:
                raise AlreadyCancelledError(f"{reservation_id} is already cancelled")
            reservation.cancelled = True
            self._reservations.save(reservation)
            log.info("cancelled reservation %s", reservation_id)

    def return_vehicle(self, reservation_id: str, actual_return: date) -> float:
        """Close out a rental. Returns the late fee (0.0 when on time)."""
        reservation = self._reservations.get(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError(f"no reservation {reservation_id}")
        if reservation.cancelled:
            raise RentalError(f"cannot return cancelled reservation {reservation_id}")
        late_days = max(0, (actual_return - reservation.end_date).days)
        fee = self._pricing.late_fee(late_days, self._config)
        log.info("return %s: %d day(s) late, fee $%.2f",
                 reservation_id, late_days, fee)
        return fee

    def quote(self, reservation_id: str) -> float:
        reservation = self._reservations.get(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError(f"no reservation {reservation_id}")
        vehicle = self._fleet.get(reservation.vehicle_id)
        return self._pricing.quote(vehicle, reservation, self._config)

    # -- helpers --------------------------------------------------------

    def _check_range(self, start: date, end: date) -> None:
        if end <= start:
            raise InvalidDateRangeError(f"end {end} must be after start {start}")
