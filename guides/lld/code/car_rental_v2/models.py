"""Version 2 domain models.

Nothing here edits a version 1 class. ElectricVehicle *extends* Vehicle, so
the v1 fleet, search and pricing accept it unchanged. Everything else is new:
the loyalty tier, the physical vehicle state, branches, trips, damage, and
the line items a quote or a return produces.
"""
from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from car_rental import Vehicle


class LoyaltyTier(Enum):
    NONE = "none"
    SILVER = "silver"
    GOLD = "gold"


@dataclass(kw_only=True)
class ElectricVehicle(Vehicle):
    """A Vehicle with a battery. kw_only keeps the parent's positional order."""
    battery_kwh: float
    charge_pct: int


class VehicleState(Enum):
    AVAILABLE = "available"
    ON_RENT = "on_rent"
    AWAITING_INSPECTION = "awaiting_inspection"
    MAINTENANCE = "maintenance"
    CHARGING = "charging"
    RETIRED = "retired"


@dataclass(frozen=True)
class Transition:
    on: date
    from_state: VehicleState
    to_state: VehicleState
    reason: str


@dataclass
class VehicleStatus:
    """Where a car physically is and what it is doing right now."""
    vehicle_id: str
    state: VehicleState
    branch_id: str
    history: list[Transition] = field(default_factory=list)


@dataclass(frozen=True)
class Branch:
    branch_id: str
    name: str


class TripStage(Enum):
    BOOKED = "booked"
    PICKED_UP = "picked_up"
    RETURNED = "returned"
    CLOSED = "closed"
    CANCELLED = "cancelled"


@dataclass
class Trip:
    """The v2 facts about a v1 Reservation, keyed by the same id."""
    reservation_id: str
    vehicle_id: str
    customer_name: str
    start_date: date
    end_date: date
    pickup_branch: str
    dropoff_branch: str
    quoted_total: float = 0.0   # locked at booking time
    late_fee: float = 0.0
    stage: TripStage = TripStage.BOOKED

    @property
    def one_way(self) -> bool:
        return self.pickup_branch != self.dropoff_branch


class DamageKind(Enum):
    SCRATCH = "scratch"
    DENT = "dent"
    CRACKED_GLASS = "cracked_glass"
    INTERIOR_STAIN = "interior_stain"


@dataclass(frozen=True)
class Damage:
    kind: DamageKind
    panel: str   # where on the car: "front bumper", "rear left door"


@dataclass(frozen=True)
class InspectionReport:
    """What the agent records when the car comes back."""
    damages: frozenset[Damage] = frozenset()
    charge_pct: int | None = None   # required for an ElectricVehicle


@dataclass(frozen=True)
class PriceLine:
    label: str
    amount: float


@dataclass(frozen=True)
class Quote:
    lines: tuple[PriceLine, ...]

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)
