"""Dynamic pricing as a chain of rules.

RuleChainPricing *is* a v1 PricingStrategy, so the untouched v1 RentalService
accepts it through its constructor. It starts from the v1 StandardPricing
quote and lets each rule add one line: a surcharge (positive) or a discount
(negative). A new rule is a new class appended to the list.

Order is part of the configuration: surcharges first, then percentage
discounts (which see the surcharged subtotal), then flat fees nobody discounts.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from car_rental import (
    FleetRepository,
    PricingStrategy,
    RentalConfig,
    Reservation,
    ReservationRepository,
    StandardPricing,
    Vehicle,
    VehicleCategory,
)

from .config import PricingRulesConfig
from .models import LoyaltyTier, PriceLine, Quote

log = logging.getLogger(__name__)


# -- the data sources the rules need ---------------------------------------

class UtilisationSource(ABC):
    @abstractmethod
    def utilisation(self, category: VehicleCategory, start: date, end: date,
                    exclude_vehicle_id: str) -> float:
        """Share of the category already booked for [start, end), 0.0..1.0."""


class FleetUtilisation(UtilisationSource):
    """Reads the v1 repositories. The car being priced does not count itself."""

    def __init__(self, fleet: FleetRepository, reservations: ReservationRepository):
        self._fleet = fleet
        self._reservations = reservations

    def utilisation(self, category: VehicleCategory, start: date, end: date,
                    exclude_vehicle_id: str) -> float:
        cars = self._fleet.by_category(category)
        if not cars:
            return 0.0
        busy = sum(1 for v in cars
                   if v.vehicle_id != exclude_vehicle_id
                   and self._reservations.has_overlap(v.vehicle_id, start, end))
        return busy / len(cars)


class LoyaltyDirectory(ABC):
    @abstractmethod
    def tier_for(self, customer_name: str) -> LoyaltyTier: ...


class InMemoryLoyalty(LoyaltyDirectory):
    def __init__(self, tiers: dict[str, LoyaltyTier] | None = None):
        self._lock = threading.Lock()   # guards _tiers
        self._tiers = dict(tiers or {})

    def set_tier(self, customer_name: str, tier: LoyaltyTier) -> None:
        with self._lock:
            self._tiers[customer_name] = tier

    def tier_for(self, customer_name: str) -> LoyaltyTier:
        with self._lock:
            return self._tiers.get(customer_name, LoyaltyTier.NONE)


# -- the rules ----------------------------------------------------------------

@dataclass(frozen=True)
class PricingContext:
    vehicle: Vehicle
    reservation: Reservation
    daily_rate: float
    utilisation: float
    tier: LoyaltyTier
    rules: PricingRulesConfig

    @property
    def base(self) -> float:
        """Days x daily rate: the part surcharges scale. Add-ons never surge."""
        return self.reservation.days * self.daily_rate

    def dates(self) -> list[date]:
        start = self.reservation.start_date
        return [start + timedelta(days=i) for i in range(self.reservation.days)]


class PricingRule(ABC):
    @abstractmethod
    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        """One line to add to the quote, or None when the rule does not apply."""


class WeekendRule(PricingRule):
    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        weekend = sum(1 for d in ctx.dates() if d.weekday() in ctx.rules.weekend_days)
        if weekend == 0:
            return None
        extra = weekend * ctx.daily_rate * (ctx.rules.weekend_multiplier - 1)
        return PriceLine(f"weekend x{weekend}", round(extra, 2))


class SurgeRule(PricingRule):
    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        for threshold, multiplier in ctx.rules.surge_tiers:
            if ctx.utilisation >= threshold:
                extra = ctx.base * (multiplier - 1)
                return PriceLine(f"surge ({ctx.utilisation:.0%} booked)",
                                 round(extra, 2))
        return None


class LongRentalDiscount(PricingRule):
    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        if ctx.reservation.days < ctx.rules.long_rental_min_days:
            return None
        cut = subtotal * ctx.rules.long_rental_discount
        return PriceLine(f"long rental ({ctx.reservation.days} days)", -round(cut, 2))


class LoyaltyDiscount(PricingRule):
    def adjust(self, ctx: PricingContext, subtotal: float) -> PriceLine | None:
        pct = ctx.rules.loyalty_discounts.get(ctx.tier, 0.0)
        if pct == 0.0:
            return None
        return PriceLine(f"loyalty {ctx.tier.name}", -round(subtotal * pct, 2))


# -- the chain ----------------------------------------------------------------

class RuleChainPricing(PricingStrategy):
    def __init__(self, rules: Sequence[PricingRule], rules_config: PricingRulesConfig,
                 utilisation: UtilisationSource, loyalty: LoyaltyDirectory,
                 base: PricingStrategy | None = None):
        self._rules = list(rules)
        self._rules_config = rules_config
        self._utilisation = utilisation
        self._loyalty = loyalty
        self._base = base or StandardPricing()

    def explain(self, vehicle: Vehicle, reservation: Reservation,
                config: RentalConfig) -> Quote:
        standard = self._base.quote(vehicle, reservation, config)
        ctx = PricingContext(
            vehicle=vehicle,
            reservation=reservation,
            daily_rate=config.daily_rates[vehicle.category],
            utilisation=self._utilisation.utilisation(
                vehicle.category, reservation.start_date, reservation.end_date,
                vehicle.vehicle_id),
            tier=self._loyalty.tier_for(reservation.customer_name),
            rules=self._rules_config,
        )
        lines = [PriceLine("standard", standard)]
        subtotal = standard
        for rule in self._rules:
            line = rule.adjust(ctx, subtotal)
            if line is not None and line.amount != 0:
                lines.append(line)
                subtotal = round(subtotal + line.amount, 2)
        log.debug("quote %s: %s", reservation.reservation_id, lines)
        return Quote(tuple(lines))

    # The two methods v1 calls. Same signatures, same meaning: Liskov holds.
    def quote(self, vehicle: Vehicle, reservation: Reservation,
              config: RentalConfig) -> float:
        return self.explain(vehicle, reservation, config).total

    def late_fee(self, late_days: int, config: RentalConfig) -> float:
        return self._base.late_fee(late_days, config)
