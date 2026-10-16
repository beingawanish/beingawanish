"""Domain models.

A reservation holds a half-open date window: [start_date, end_date). The car
is yours from the start date up to, but not including, the end date. That
one choice makes back-to-back bookings fall out naturally: a reservation
ending Nov 5 and another starting Nov 5 do not overlap, because the end is
exclusive.
"""
from dataclasses import dataclass, field
from datetime import date

from .config import VehicleCategory


@dataclass
class Vehicle:
    vehicle_id: str
    category: VehicleCategory
    make: str
    model: str
    year: int


@dataclass(frozen=True)
class AddOns:
    insurance: bool = False
    gps: bool = False


@dataclass
class Reservation:
    reservation_id: str
    vehicle_id: str
    customer_name: str
    start_date: date  # inclusive
    end_date: date    # exclusive: [start_date, end_date)
    add_ons: AddOns = field(default_factory=AddOns)
    cancelled: bool = False

    @property
    def days(self) -> int:
        return (self.end_date - self.start_date).days

    def conflicts_with(self, start: date, end: date) -> bool:
        """True iff window [start, end) overlaps this reservation's window.

        Two half-open intervals overlap exactly when each one starts before
        the other ends: new.start < existing.end and existing.start < new.end.
        Touching at a boundary (one ends Nov 5, the other starts Nov 5) is
        not a conflict.
        """
        return self.start_date < end and start < self.end_date
