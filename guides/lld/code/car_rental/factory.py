"""Factory: the one place that builds a valid Reservation.

Construction plus validation live together here, so the service never holds
a half-checked reservation. Every rule about "what counts as a reservable
window" is in create(); the service only asks "does it conflict?".
"""
import uuid
from datetime import date

from .clock import Clock
from .errors import InvalidDateRangeError, ReservationInPastError, VehicleNotFoundError
from .models import AddOns, Reservation
from .repositories import FleetRepository


class ReservationFactory:
    def __init__(self, fleet: FleetRepository, clock: Clock):
        self._fleet = fleet
        self._clock = clock

    def create(self, vehicle_id: str, customer_name: str,
               start: date, end: date, add_ons: AddOns | None = None) -> Reservation:
        if not customer_name or not customer_name.strip():
            raise ValueError("customer_name must not be blank")
        if self._fleet.get(vehicle_id) is None:
            raise VehicleNotFoundError(f"no vehicle {vehicle_id}")
        if end <= start:
            raise InvalidDateRangeError(
                f"end {end} must be after start {start}")
        if start < self._clock.today():
            raise ReservationInPastError(
                f"start {start} is in the past (today is {self._clock.today()})")
        return Reservation(
            reservation_id=uuid.uuid4().hex[:8],
            vehicle_id=vehicle_id,
            customer_name=customer_name.strip(),
            start_date=start,
            end_date=end,
            add_ons=add_ons or AddOns(),
        )
