"""Every tunable number in the system, in one frozen, validated dataclass.

Distances are kilometres on a flat city grid; money is Decimal; durations
are seconds. Nothing else in the package contains a literal tariff or radius.
"""
from dataclasses import dataclass
from decimal import Decimal

from .errors import InvalidInputError


@dataclass(frozen=True)
class RideConfig:
    # spatial index and matching
    grid_cell_km: float = 1.0
    search_radius_km: float = 3.0
    rating_penalty_km_per_star: float = 0.5
    default_rating: float = 5.0
    max_stars: int = 5
    # dispatch
    offer_timeout_s: float = 15.0
    max_offer_attempts: int = 3
    # fares
    base_fare: Decimal = Decimal("2.50")
    per_km: Decimal = Decimal("1.20")
    per_minute: Decimal = Decimal("0.30")
    minimum_fare: Decimal = Decimal("5.00")
    avg_speed_kmh: float = 30.0
    # surge
    surge_step: Decimal = Decimal("0.5")
    surge_cap: Decimal = Decimal("2.5")
    # cancellation
    free_cancel_window_s: float = 120.0
    rider_cancel_fee: Decimal = Decimal("4.00")

    def __post_init__(self) -> None:
        positive = {
            "grid_cell_km": self.grid_cell_km,
            "search_radius_km": self.search_radius_km,
            "offer_timeout_s": self.offer_timeout_s,
            "max_offer_attempts": self.max_offer_attempts,
            "avg_speed_kmh": self.avg_speed_kmh,
            "max_stars": self.max_stars,
        }
        for name, value in positive.items():
            if value <= 0:
                raise InvalidInputError(f"{name} must be positive, got {value}")
        if not 1 <= self.default_rating <= self.max_stars:
            raise InvalidInputError("default_rating must be within 1..max_stars")
        if self.surge_cap < 1:
            raise InvalidInputError("surge_cap must be at least 1")
        for name in ("base_fare", "per_km", "per_minute", "minimum_fare",
                     "rider_cancel_fee", "surge_step"):
            if getattr(self, name) < 0:
                raise InvalidInputError(f"{name} must not be negative")
        if self.free_cancel_window_s < 0 or self.rating_penalty_km_per_star < 0:
            raise InvalidInputError("windows and penalties must not be negative")
