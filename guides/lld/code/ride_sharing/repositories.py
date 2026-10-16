"""Storage behind interfaces: riders, drivers, trips.

The driver repository owns one extra operation, claim(), an atomic
compare-and-set on driver status. It is the line that stops a driver from
ever being handed two riders.
"""
import threading
from abc import ABC, abstractmethod

from .errors import DriverNotFoundError, DuplicateIdError, RiderNotFoundError, TripNotFoundError
from .models import Driver, DriverStatus, Location, Rider, Trip, TripStatus


class RiderRepository(ABC):
    @abstractmethod
    def add(self, rider: Rider) -> None: ...

    @abstractmethod
    def get(self, rider_id: str) -> Rider: ...


class DriverRepository(ABC):
    @abstractmethod
    def add(self, driver: Driver) -> None: ...

    @abstractmethod
    def get(self, driver_id: str) -> Driver: ...

    @abstractmethod
    def claim(self, driver_id: str, expected: DriverStatus, new: DriverStatus) -> bool:
        """Set status to new only if it is currently expected. Atomic."""

    @abstractmethod
    def move(self, driver_id: str, location: Location) -> None: ...


class TripRepository(ABC):
    @abstractmethod
    def add(self, trip: Trip) -> None: ...

    @abstractmethod
    def get(self, trip_id: str) -> Trip: ...

    @abstractmethod
    def with_status(self, status: TripStatus) -> list[Trip]: ...


class InMemoryRiders(RiderRepository):
    def __init__(self) -> None:
        self._riders: dict[str, Rider] = {}
        self._lock = threading.Lock()  # guards _riders

    def add(self, rider: Rider) -> None:
        with self._lock:
            if rider.rider_id in self._riders:
                raise DuplicateIdError(f"rider {rider.rider_id} already exists")
            self._riders[rider.rider_id] = rider

    def get(self, rider_id: str) -> Rider:
        with self._lock:
            try:
                return self._riders[rider_id]
            except KeyError:
                raise RiderNotFoundError(f"no rider {rider_id}") from None


class InMemoryDrivers(DriverRepository):
    def __init__(self) -> None:
        self._drivers: dict[str, Driver] = {}
        self._lock = threading.Lock()  # guards _drivers, Driver.status, Driver.location

    def add(self, driver: Driver) -> None:
        with self._lock:
            if driver.driver_id in self._drivers:
                raise DuplicateIdError(f"driver {driver.driver_id} already exists")
            self._drivers[driver.driver_id] = driver

    def get(self, driver_id: str) -> Driver:
        with self._lock:
            try:
                return self._drivers[driver_id]
            except KeyError:
                raise DriverNotFoundError(f"no driver {driver_id}") from None

    def claim(self, driver_id: str, expected: DriverStatus, new: DriverStatus) -> bool:
        with self._lock:
            driver = self._drivers.get(driver_id)
            if driver is None:
                raise DriverNotFoundError(f"no driver {driver_id}")
            if driver.status is not expected:
                return False
            driver.status = new
            return True

    def move(self, driver_id: str, location: Location) -> None:
        with self._lock:
            driver = self._drivers.get(driver_id)
            if driver is None:
                raise DriverNotFoundError(f"no driver {driver_id}")
            driver.location = location


class InMemoryTrips(TripRepository):
    def __init__(self) -> None:
        self._trips: dict[str, Trip] = {}
        self._lock = threading.Lock()  # guards _trips (not the trips' fields)

    def add(self, trip: Trip) -> None:
        with self._lock:
            if trip.trip_id in self._trips:
                raise DuplicateIdError(f"trip {trip.trip_id} already exists")
            self._trips[trip.trip_id] = trip

    def get(self, trip_id: str) -> Trip:
        with self._lock:
            try:
                return self._trips[trip_id]
            except KeyError:
                raise TripNotFoundError(f"no trip {trip_id}") from None

    def with_status(self, status: TripStatus) -> list[Trip]:
        with self._lock:
            return [t for t in self._trips.values() if t.status is status]
