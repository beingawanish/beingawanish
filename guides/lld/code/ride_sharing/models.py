"""Domain objects: where things are, who they are, and what a trip carries.

These classes hold data and answer small questions about themselves. They
never decide who gets a ride; that is the dispatcher's job.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum


@dataclass(frozen=True)
class Location:
    """A point on the city grid, in kilometres from an arbitrary origin."""

    x_km: float
    y_km: float

    def distance_to(self, other: "Location") -> float:
        return math.hypot(self.x_km - other.x_km, self.y_km - other.y_km)


class DriverStatus(Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    OFFERED = "OFFERED"      # holding exactly one pending offer
    ON_TRIP = "ON_TRIP"      # matched, arriving, or driving


class TripStatus(Enum):
    REQUESTED = "REQUESTED"
    MATCHED = "MATCHED"
    DRIVER_ARRIVING = "DRIVER_ARRIVING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    def __str__(self) -> str:
        return self.value


class CancelledBy(Enum):
    RIDER = "RIDER"
    DRIVER = "DRIVER"
    SYSTEM = "SYSTEM"


@dataclass
class RatingBook:
    """Running total of stars received. Average falls back to a default."""

    total: int = 0
    count: int = 0

    def add(self, stars: int) -> None:
        self.total += stars
        self.count += 1

    def average(self, default: float) -> float:
        return self.total / self.count if self.count else default


@dataclass
class Rider:
    rider_id: str
    name: str
    ratings: RatingBook = field(default_factory=RatingBook)


@dataclass
class Driver:
    driver_id: str
    name: str
    location: Location
    status: DriverStatus = DriverStatus.OFFLINE
    ratings: RatingBook = field(default_factory=RatingBook)


@dataclass
class Trip:
    trip_id: str
    rider_id: str
    pickup: Location
    dropoff: Location
    requested_at: datetime
    surge: Decimal
    status: TripStatus = TripStatus.REQUESTED
    driver_id: str | None = None
    matched_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancelled_by: CancelledBy | None = None
    cancel_reason: str = ""
    fare: Decimal | None = None
    cancellation_fee: Decimal = Decimal("0.00")
    offer_attempts: int = 0
    declined_driver_ids: set[str] = field(default_factory=set)
    rider_rated: bool = False
    driver_rated: bool = False

    @property
    def distance_km(self) -> float:
        return self.pickup.distance_to(self.dropoff)


@dataclass(frozen=True)
class Offer:
    """One driver, one trip, one deadline."""

    offer_id: str
    trip_id: str
    driver_id: str
    expires_at: datetime

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


@dataclass(frozen=True)
class FareQuote:
    distance_km: float
    estimated_minutes: float
    surge: Decimal
    estimate: Decimal
