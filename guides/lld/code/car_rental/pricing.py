"""Pricing as a Strategy.

The service asks "what does this cost?" without knowing the formula. A new
formula (weekend rates, loyalty discounts) is a new class implementing
PricingStrategy, not an edit to existing code.
"""
from abc import ABC, abstractmethod

from .config import RentalConfig
from .models import AddOns, Reservation, Vehicle


class PricingStrategy(ABC):
    @abstractmethod
    def quote(self, vehicle: Vehicle, reservation: Reservation,
              config: RentalConfig) -> float:
        ...

    @abstractmethod
    def late_fee(self, late_days: int, config: RentalConfig) -> float:
        ...


class StandardPricing(PricingStrategy):
    """daily rate x days, plus per-day add-ons, plus a per-day late fee."""

    def quote(self, vehicle: Vehicle, reservation: Reservation,
              config: RentalConfig) -> float:
        days = reservation.days
        total = days * config.daily_rates[vehicle.category]
        if reservation.add_ons.insurance:
            total += days * config.add_ons.insurance_per_day
        if reservation.add_ons.gps:
            total += days * config.add_ons.gps_per_day
        return round(total, 2)

    def late_fee(self, late_days: int, config: RentalConfig) -> float:
        if late_days <= 0:
            return 0.0
        return round(late_days * config.add_ons.late_fee_per_day, 2)
