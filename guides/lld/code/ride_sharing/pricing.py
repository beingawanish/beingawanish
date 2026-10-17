"""Money rules, each behind its own interface.

SurgePolicy turns supply and demand into a multiplier. FareStrategy turns a
distance, a duration and that multiplier into a fare. CancellationPolicy
decides whether a cancelled trip costs anything. All three read RideConfig.
"""
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from .config import RideConfig
from .errors import InvalidInputError
from .models import CancelledBy, Trip

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ONE = Decimal("1.0")


def to_money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class SurgePolicy(ABC):
    @abstractmethod
    def multiplier(self, demand: int, supply: int) -> Decimal:
        """demand = open requests near the pickup, supply = free drivers there."""


class SupplyDemandSurge(SurgePolicy):
    """1.0x while drivers keep up; then +surge_step per extra request per
    driver, rounded to 0.1 and capped. No drivers at all means the cap."""

    def __init__(self, config: RideConfig) -> None:
        self._config = config

    def multiplier(self, demand: int, supply: int) -> Decimal:
        if demand < 0 or supply < 0:
            raise InvalidInputError("demand and supply must not be negative")
        if demand <= supply:
            return ONE
        if supply == 0:
            return self._config.surge_cap
        ratio = Decimal(demand) / Decimal(supply)
        raw = ONE + self._config.surge_step * (ratio - ONE)
        return min(self._config.surge_cap, raw.quantize(TENTH, rounding=ROUND_HALF_UP))


class FareStrategy(ABC):
    @abstractmethod
    def fare(self, distance_km: float, minutes: float, surge: Decimal) -> Decimal: ...


class StandardFare(FareStrategy):
    """max(base + per_km*km + per_minute*min, minimum) * surge, to the cent."""

    def __init__(self, config: RideConfig) -> None:
        self._config = config

    def fare(self, distance_km: float, minutes: float, surge: Decimal) -> Decimal:
        if distance_km < 0 or minutes < 0:
            raise InvalidInputError("distance and minutes must not be negative")
        c = self._config
        subtotal = (c.base_fare
                    + c.per_km * Decimal(str(round(distance_km, 3)))
                    + c.per_minute * Decimal(str(round(minutes, 2))))
        return to_money(max(subtotal, c.minimum_fare) * surge)


class CancellationPolicy(ABC):
    @abstractmethod
    def fee(self, trip: Trip, by: CancelledBy, now: datetime) -> Decimal: ...


class GracePeriodCancellation(CancellationPolicy):
    """Riders cancel free until free_cancel_window_s after a driver accepts.
    After that they pay rider_cancel_fee. Drivers and the system never
    charge the rider."""

    def __init__(self, config: RideConfig) -> None:
        self._config = config

    def fee(self, trip: Trip, by: CancelledBy, now: datetime) -> Decimal:
        if by is not CancelledBy.RIDER or trip.matched_at is None:
            return to_money(Decimal(0))
        waited = (now - trip.matched_at).total_seconds()
        if waited <= self._config.free_cancel_window_s:
            return to_money(Decimal(0))
        return to_money(self._config.rider_cancel_fee)
