"""RentalDesk: the version 2 use cases, composed around the v1 service.

The v1 RentalService still does what it always did: validate, check for
overlaps, store reservations, compute late fees. The desk adds the steps v1
never had (branches, the car's physical state, the deposit, the inspection)
and calls v1 for the rest. One RLock makes each use case atomic across all
the parts it touches.
"""
import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from car_rental import (
    AddOns,
    Clock,
    DuplicateVehicleError,
    FleetRepository,
    RentalConfig,
    RentalService,
    ReservationRepository,
    Vehicle,
    VehicleCategory,
)

from .branches import BranchNetwork, TripRepository
from .config import V2Config
from .errors import RentalStageError, TripNotFoundError, VehicleNotReadyError
from .ev import ReturnRule
from .inspection import DamageInspector
from .lifecycle import VehicleLifecycle
from .models import (
    Damage,
    ElectricVehicle,
    InspectionReport,
    PriceLine,
    Quote,
    Trip,
    TripStage,
    VehicleState,
    VehicleStatus,
)
from .payments import PaymentRecord, PaymentService, Settlement
from .pricing_rules import RuleChainPricing

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReturnSummary:
    reservation_id: str
    quoted_total: float
    extras: tuple[PriceLine, ...]
    final: float
    settlement: Settlement
    next_state: VehicleState


class RentalDesk:
    def __init__(self, *, rental: RentalService, fleet: FleetRepository,
                 reservations: ReservationRepository,
                 pricing: RuleChainPricing, lifecycle: VehicleLifecycle,
                 network: BranchNetwork, trips: TripRepository,
                 inspector: DamageInspector, return_rules: Sequence[ReturnRule],
                 payments: PaymentService, clock: Clock,
                 config: V2Config, rental_config: RentalConfig):
        self._rental = rental
        self._fleet = fleet
        self._reservations = reservations   # the same repo v1 was given
        self._pricing = pricing
        self._lifecycle = lifecycle
        self._network = network
        self._trips = trips
        self._inspector = inspector
        self._return_rules = list(return_rules)
        self._payments = payments
        self._clock = clock
        self._config = config
        self._rental_config = rental_config
        self._lock = threading.RLock()   # one use case at a time, end to end

    # -- fleet --------------------------------------------------------------

    def add_vehicle(self, vehicle_id: str, category: VehicleCategory, make: str,
                    model: str, year: int, branch_id: str) -> Vehicle:
        with self._lock:
            self._network.require(branch_id)
            vehicle = self._rental.add_vehicle(vehicle_id, category, make, model, year)
            self._lifecycle.register(vehicle.vehicle_id, branch_id)
            return vehicle

    def add_ev(self, vehicle_id: str, category: VehicleCategory, make: str,
               model: str, year: int, branch_id: str, *,
               battery_kwh: float, charge_pct: int) -> ElectricVehicle:
        if battery_kwh <= 0:
            raise ValueError("battery_kwh must be positive")
        if not 0 <= charge_pct <= 100:
            raise ValueError("charge_pct must be within 0..100")
        with self._lock:
            self._network.require(branch_id)
            if self._fleet.get(vehicle_id) is not None:
                raise DuplicateVehicleError(f"vehicle {vehicle_id} already exists")
            ev = ElectricVehicle(vehicle_id, category, make, model, year,
                                 battery_kwh=battery_kwh, charge_pct=charge_pct)
            self._fleet.add(ev)
            self._lifecycle.register(vehicle_id, branch_id)
            log.info("added EV %s at %d%%", vehicle_id, charge_pct)
            return ev

    # -- booking ------------------------------------------------------------

    def search(self, category: VehicleCategory, start: date, end: date,
               branch_id: str) -> list[Vehicle]:
        """v1 search, then: not retired or in the workshop, and at the branch."""
        self._network.require(branch_id)
        blocked = {VehicleState.RETIRED, VehicleState.MAINTENANCE}
        return [v for v in self._rental.search_available(category, start, end)
                if self._lifecycle.status(v.vehicle_id).state not in blocked
                and self._network.expected_branch(v.vehicle_id, start) == branch_id]

    def book(self, vehicle_id: str, customer_name: str, start: date, end: date,
             pickup_branch: str, dropoff_branch: str | None = None,
             add_ons: AddOns | None = None) -> Trip:
        dropoff_branch = dropoff_branch or pickup_branch
        with self._lock:
            if self._lifecycle.status(vehicle_id).state is VehicleState.RETIRED:
                raise VehicleNotReadyError(f"{vehicle_id} is retired")
            self._network.check_route(vehicle_id, start, end,
                                      pickup_branch, dropoff_branch)
            reservation = self._rental.reserve(vehicle_id, customer_name,
                                               start, end, add_ons)
            trip = Trip(reservation.reservation_id, vehicle_id,
                        reservation.customer_name, start, end,
                        pickup_branch, dropoff_branch)
            self._trips.add(trip)   # before pricing: OneWayFeeRule reads it
            trip.quoted_total = self.quote(trip.reservation_id).total
            self._trips.save(trip)
            log.info("booked %s, price locked at $%.2f",
                     trip.reservation_id, trip.quoted_total)
            return trip

    def quote(self, reservation_id: str) -> Quote:
        """Today's itemised price. The trip keeps the total locked at booking."""
        trip = self._trip(reservation_id)
        reservation = self._reservations.get(reservation_id)
        vehicle = self._fleet.get(trip.vehicle_id)
        return self._pricing.explain(vehicle, reservation, self._rental_config)

    def cancel(self, reservation_id: str) -> None:
        with self._lock:
            trip = self._trip(reservation_id)
            self._require_stage(trip, TripStage.BOOKED)
            self._rental.cancel(reservation_id)
            trip.stage = TripStage.CANCELLED
            self._trips.save(trip)

    # -- the rental itself --------------------------------------------------

    def pick_up(self, reservation_id: str,
                walkaround: Iterable[Damage] = ()) -> PaymentRecord:
        with self._lock:
            trip = self._trip(reservation_id)
            self._require_stage(trip, TripStage.BOOKED)
            today = self._clock.today()
            if not trip.start_date <= today < trip.end_date:
                raise RentalStageError(
                    f"pickup for {reservation_id} is {trip.start_date}, today is {today}")
            vehicle = self._fleet.get(trip.vehicle_id)
            self._check_ready(vehicle, trip.pickup_branch)
            deposit = self._config.payments.deposits[vehicle.category]
            record = self._payments.place_hold(reservation_id,
                                               trip.quoted_total + deposit)
            self._lifecycle.transition(vehicle.vehicle_id, VehicleState.ON_RENT,
                                       f"pickup {reservation_id}")
            self._inspector.record(vehicle.vehicle_id, walkaround)
            trip.stage = TripStage.PICKED_UP
            self._trips.save(trip)
            return record

    def return_vehicle(self, reservation_id: str) -> None:
        """Keys back at the drop-off branch. The car waits for inspection."""
        with self._lock:
            trip = self._trip(reservation_id)
            self._require_stage(trip, TripStage.PICKED_UP)
            self._lifecycle.transition(trip.vehicle_id, VehicleState.AWAITING_INSPECTION,
                                       f"return {reservation_id}",
                                       branch_id=trip.dropoff_branch)
            trip.late_fee = self._rental.return_vehicle(reservation_id,
                                                        self._clock.today())
            trip.stage = TripStage.RETURNED
            self._trips.save(trip)

    def complete_inspection(self, reservation_id: str,
                            report: InspectionReport) -> ReturnSummary:
        with self._lock:
            trip = self._trip(reservation_id)
            self._require_stage(trip, TripStage.RETURNED)
            vehicle = self._fleet.get(trip.vehicle_id)
            extras: list[PriceLine] = []
            if trip.late_fee > 0:
                extras.append(PriceLine("late return", trip.late_fee))
            for rule in self._return_rules:
                extras.extend(rule.charges(vehicle, report))
            assessment = self._inspector.assess(vehicle.vehicle_id, report)
            extras.extend(assessment.lines)
            final = round(trip.quoted_total + sum(x.amount for x in extras), 2)
            # Money first. If the gateway times out, nothing below has run,
            # and a retry re-prices the same report with the same keys.
            settlement = self._payments.settle(reservation_id, final)
            self._inspector.record(vehicle.vehicle_id, assessment.new_damage)
            if isinstance(vehicle, ElectricVehicle):
                vehicle.charge_pct = report.charge_pct
                self._fleet.add(vehicle)
            next_state = self._next_state(vehicle, assessment.needs_repair)
            self._lifecycle.transition(vehicle.vehicle_id, next_state,
                                       f"inspected {reservation_id}")
            trip.stage = TripStage.CLOSED
            self._trips.save(trip)
            return ReturnSummary(reservation_id, trip.quoted_total, tuple(extras),
                                 final, settlement, next_state)

    # -- workshop and chargers ---------------------------------------------

    def send_to_maintenance(self, vehicle_id: str, reason: str) -> None:
        self._lifecycle.transition(vehicle_id, VehicleState.MAINTENANCE, reason)

    def finish_maintenance(self, vehicle_id: str) -> None:
        with self._lock:
            self._lifecycle.transition(vehicle_id, VehicleState.AVAILABLE, "repaired")
            self._inspector.repair(vehicle_id)

    def finish_charging(self, vehicle_id: str, charge_pct: int) -> None:
        with self._lock:
            vehicle = self._fleet.get(vehicle_id)
            if not isinstance(vehicle, ElectricVehicle):
                raise ValueError(f"{vehicle_id} is not electric")
            if charge_pct < self._config.ev.min_pickup_charge_pct or charge_pct > 100:
                raise ValueError(f"charge_pct {charge_pct} is not rentable")
            vehicle.charge_pct = charge_pct
            self._fleet.add(vehicle)
            self._lifecycle.transition(vehicle_id, VehicleState.AVAILABLE,
                                       f"charged to {charge_pct}%")

    def retire(self, vehicle_id: str) -> None:
        self._lifecycle.transition(vehicle_id, VehicleState.RETIRED, "retired")

    def status(self, vehicle_id: str) -> VehicleStatus:
        return self._lifecycle.status(vehicle_id)

    # -- helpers ------------------------------------------------------------

    def _trip(self, reservation_id: str) -> Trip:
        trip = self._trips.get(reservation_id)
        if trip is None:
            raise TripNotFoundError(f"no trip {reservation_id}")
        return trip

    @staticmethod
    def _require_stage(trip: Trip, stage: TripStage) -> None:
        if trip.stage is not stage:
            raise RentalStageError(
                f"{trip.reservation_id} is {trip.stage.name}, expected {stage.name}")

    def _check_ready(self, vehicle: Vehicle, branch_id: str) -> None:
        status = self._lifecycle.status(vehicle.vehicle_id)
        if status.state is not VehicleState.AVAILABLE:
            raise VehicleNotReadyError(f"{vehicle.vehicle_id} is {status.state.name}")
        if status.branch_id != branch_id:
            raise VehicleNotReadyError(
                f"{vehicle.vehicle_id} is at {status.branch_id}, not {branch_id}")
        if (isinstance(vehicle, ElectricVehicle)
                and vehicle.charge_pct < self._config.ev.min_pickup_charge_pct):
            raise VehicleNotReadyError(
                f"{vehicle.vehicle_id} is at {vehicle.charge_pct}% charge")

    def _next_state(self, vehicle: Vehicle, needs_repair: bool) -> VehicleState:
        if needs_repair:
            return VehicleState.MAINTENANCE
        if (isinstance(vehicle, ElectricVehicle)
                and vehicle.charge_pct < self._config.ev.min_pickup_charge_pct):
            return VehicleState.CHARGING
        return VehicleState.AVAILABLE
