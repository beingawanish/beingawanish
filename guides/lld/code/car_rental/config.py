"""Configuration: vehicle categories and every price the business charges.

Rates live here, in one frozen dataclass, so pricing logic never contains a
literal dollar amount. Change a rate in one place; every quote follows.
"""
from dataclasses import dataclass, field
from enum import Enum


class VehicleCategory(Enum):
    ECONOMY = "economy"
    SUV = "suv"
    LUXURY = "luxury"


@dataclass(frozen=True)
class AddOnRates:
    insurance_per_day: float = 9.99
    gps_per_day: float = 4.99
    late_fee_per_day: float = 79.99


@dataclass(frozen=True)
class RentalConfig:
    daily_rates: dict[VehicleCategory, float] = field(default_factory=lambda: {
        VehicleCategory.ECONOMY: 49.99,
        VehicleCategory.SUV: 89.99,
        VehicleCategory.LUXURY: 149.99,
    })
    add_ons: AddOnRates = field(default_factory=AddOnRates)
