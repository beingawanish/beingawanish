"""Multi-branch pickup and drop-off.

A Trip records the branches for a v1 Reservation, keyed by the same id, so
Reservation itself never changes. BranchNetwork answers two questions:
where will this car be on a given day, and does a new trip fit the car's
route without stranding a later booking? OneWayFeeRule adds the fee as one
more link in the pricing chain.
"""
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import date

from .config import BranchConfig
from .errors import BranchMismatchError, UnknownBranchError
from .lifecycle import VehicleLifecycle
from .models import Branch, PriceLine, Trip, TripStage
from .pricing_rules import PricingContext, PricingRule

# Trips whose drop-off has not happened yet. Once a car is returned, the
# lifecycle status already holds its branch.
_OPEN = frozenset({TripStage.BOOKED, TripStage.PICKED_UP})


class TripRepository(ABC):
    @abstractmethod
    def add(self, trip: Trip) -> None: ...
    @abstractmethod
    def get(self, reservation_id: str) -> Trip | None: ...
    @abstractmethod
    def save(self, trip: Trip) -> None: ...
    @abstractmethod
    def for_vehicle(self, vehicle_id: str) -> list[Trip]:
        """Trips for the vehicle that are not cancelled."""


class InMemoryTrips(TripRepository):
    def __init__(self):
        self._lock = threading.Lock()   # guards _trips
        self._trips: dict[str, Trip] = {}

    def add(self, trip: Trip) -> None:
        with self._lock:
            self._trips[trip.reservation_id] = trip

    def get(self, reservation_id: str) -> Trip | None:
        with self._lock:
            return self._trips.get(reservation_id)

    def save(self, trip: Trip) -> None:
        self.add(trip)

    def for_vehicle(self, vehicle_id: str) -> list[Trip]:
        with self._lock:
            return [t for t in self._trips.values()
                    if t.vehicle_id == vehicle_id
                    and t.stage is not TripStage.CANCELLED]


class BranchNetwork:
    def __init__(self, branches: Iterable[Branch], trips: TripRepository,
                 lifecycle: VehicleLifecycle, config: BranchConfig):
        self._branches = {b.branch_id: b for b in branches}
        self._trips = trips
        self._lifecycle = lifecycle
        self._config = config

    def require(self, branch_id: str) -> Branch:
        branch = self._branches.get(branch_id)
        if branch is None:
            raise UnknownBranchError(f"no branch {branch_id}")
        return branch

    def one_way_fee(self, pickup: str, dropoff: str) -> float:
        if pickup == dropoff:
            return 0.0
        return self._config.one_way_fees.get(
            (pickup, dropoff), self._config.default_one_way_fee)

    def expected_branch(self, vehicle_id: str, on: date) -> str:
        """Where the car will be on `on`: the drop-off of its latest open trip
        ending by then, or where it stands today if no open trip ends first."""
        earlier = [t for t in self._trips.for_vehicle(vehicle_id)
                   if t.stage in _OPEN and t.end_date <= on]
        if earlier:
            return max(earlier, key=lambda t: t.end_date).dropoff_branch
        return self._lifecycle.status(vehicle_id).branch_id

    def check_route(self, vehicle_id: str, start: date, end: date,
                    pickup: str, dropoff: str) -> None:
        self.require(pickup)
        self.require(dropoff)
        here = self.expected_branch(vehicle_id, start)
        if here != pickup:
            raise BranchMismatchError(
                f"{vehicle_id} will be at {here} on {start}, not {pickup}")
        later = [t for t in self._trips.for_vehicle(vehicle_id) if t.start_date >= end]
        if later:
            nxt = min(later, key=lambda t: t.start_date)
            if nxt.pickup_branch != dropoff:
                raise BranchMismatchError(
                    f"dropping {vehicle_id} at {dropoff} strands trip "
                    f"{nxt.reservation_id}, which starts at {nxt.pickup_branch} "
                    f"on {nxt.start_date}")


class OneWayFeeRule(PricingRule):
    """A flat fee. Put it after the discounts so nobody discounts it."""

    def __init__(self, network: BranchNetwork, trips: TripRepository):
        self._network = network
        self._trips = trips

    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        trip = self._trips.get(ctx.reservation.reservation_id)
        if trip is None or not trip.one_way:
            return None
        fee = self._network.one_way_fee(trip.pickup_branch, trip.dropoff_branch)
        return PriceLine(f"one-way {trip.pickup_branch}->{trip.dropoff_branch}", fee)
