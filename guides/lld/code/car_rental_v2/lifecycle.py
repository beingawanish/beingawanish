"""The vehicle lifecycle: an explicit state machine.

A Reservation says who has a car for which dates. It says nothing about the
car itself: is it on the lot, in the workshop, on a charger? That is a
separate fact with separate rules, so it gets its own table and its own class.
Every legal move is listed in TRANSITIONS; anything else raises.
"""
import logging
import threading
from abc import ABC, abstractmethod

from car_rental import Clock, VehicleNotFoundError

from .errors import InvalidTransitionError
from .models import Transition, VehicleState, VehicleStatus

log = logging.getLogger(__name__)

S = VehicleState
TRANSITIONS: dict[VehicleState, frozenset[VehicleState]] = {
    S.AVAILABLE: frozenset({S.ON_RENT, S.MAINTENANCE, S.RETIRED}),
    S.ON_RENT: frozenset({S.AWAITING_INSPECTION}),
    S.AWAITING_INSPECTION: frozenset({S.AVAILABLE, S.MAINTENANCE, S.CHARGING}),
    S.MAINTENANCE: frozenset({S.AVAILABLE, S.RETIRED}),
    S.CHARGING: frozenset({S.AVAILABLE, S.MAINTENANCE}),
    S.RETIRED: frozenset(),
}


class StatusRepository(ABC):
    @abstractmethod
    def get(self, vehicle_id: str) -> VehicleStatus | None: ...
    @abstractmethod
    def save(self, status: VehicleStatus) -> None: ...


class InMemoryStatuses(StatusRepository):
    def __init__(self):
        self._lock = threading.Lock()   # guards _statuses
        self._statuses: dict[str, VehicleStatus] = {}

    def get(self, vehicle_id: str) -> VehicleStatus | None:
        with self._lock:
            return self._statuses.get(vehicle_id)

    def save(self, status: VehicleStatus) -> None:
        with self._lock:
            self._statuses[status.vehicle_id] = status


class VehicleLifecycle:
    def __init__(self, statuses: StatusRepository, clock: Clock):
        self._statuses = statuses
        self._clock = clock
        self._lock = threading.RLock()   # makes read-check-write one step

    def register(self, vehicle_id: str, branch_id: str) -> VehicleStatus:
        status = VehicleStatus(vehicle_id, VehicleState.AVAILABLE, branch_id)
        self._statuses.save(status)
        return status

    def status(self, vehicle_id: str) -> VehicleStatus:
        status = self._statuses.get(vehicle_id)
        if status is None:
            raise VehicleNotFoundError(f"no status for vehicle {vehicle_id}")
        return status

    def transition(self, vehicle_id: str, to: VehicleState, reason: str,
                   branch_id: str | None = None) -> VehicleStatus:
        with self._lock:
            status = self.status(vehicle_id)
            if to not in TRANSITIONS[status.state]:
                raise InvalidTransitionError(
                    f"{vehicle_id}: {status.state.name} -> {to.name} is not allowed")
            status.history.append(
                Transition(self._clock.today(), status.state, to, reason))
            status.state = to
            if branch_id is not None:
                status.branch_id = branch_id
            self._statuses.save(status)
            log.info("%s -> %s (%s)", vehicle_id, to.name, reason)
            return status
