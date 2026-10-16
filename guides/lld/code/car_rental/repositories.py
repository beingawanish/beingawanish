"""Repositories: the fleet and the reservation book, behind ABCs.

has_overlap is the query the whole design hinges on: it skips cancelled
reservations (a cancellation frees its window) and delegates the interval
math to Reservation.conflicts_with, so the rule lives in exactly one place.
"""
import threading
from abc import ABC, abstractmethod
from datetime import date

from .models import Reservation, Vehicle


class FleetRepository(ABC):
    @abstractmethod
    def add(self, vehicle: Vehicle) -> None: ...
    @abstractmethod
    def get(self, vehicle_id: str) -> Vehicle | None: ...
    @abstractmethod
    def by_category(self, category) -> list[Vehicle]: ...


class InMemoryFleet(FleetRepository):
    def __init__(self):
        self._lock = threading.Lock()
        self._vehicles: dict[str, Vehicle] = {}

    def add(self, vehicle: Vehicle) -> None:
        with self._lock:
            self._vehicles[vehicle.vehicle_id] = vehicle

    def get(self, vehicle_id: str) -> Vehicle | None:
        with self._lock:
            return self._vehicles.get(vehicle_id)

    def by_category(self, category) -> list[Vehicle]:
        with self._lock:
            return [v for v in self._vehicles.values() if v.category is category]


class ReservationRepository(ABC):
    @abstractmethod
    def add(self, reservation: Reservation) -> None: ...
    @abstractmethod
    def get(self, reservation_id: str) -> Reservation | None: ...
    @abstractmethod
    def save(self, reservation: Reservation) -> None: ...
    @abstractmethod
    def for_vehicle(self, vehicle_id: str) -> list[Reservation]: ...
    @abstractmethod
    def has_overlap(self, vehicle_id: str, start: date, end: date) -> bool: ...


class InMemoryReservations(ReservationRepository):
    def __init__(self):
        self._lock = threading.Lock()
        self._reservations: dict[str, Reservation] = {}

    def add(self, reservation: Reservation) -> None:
        with self._lock:
            self._reservations[reservation.reservation_id] = reservation

    def get(self, reservation_id: str) -> Reservation | None:
        with self._lock:
            return self._reservations.get(reservation_id)

    def save(self, reservation: Reservation) -> None:
        with self._lock:
            self._reservations[reservation.reservation_id] = reservation

    def for_vehicle(self, vehicle_id: str) -> list[Reservation]:
        with self._lock:
            return [r for r in self._reservations.values()
                    if r.vehicle_id == vehicle_id and not r.cancelled]

    def has_overlap(self, vehicle_id: str, start: date, end: date) -> bool:
        with self._lock:
            return any(r.conflicts_with(start, end)
                       for r in self._reservations.values()
                       if r.vehicle_id == vehicle_id and not r.cancelled)
