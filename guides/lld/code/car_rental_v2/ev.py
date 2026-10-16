"""Return rules, and the first one: EVs must come back charged.

ReturnRule is the seam for "charge something when the car comes back".
LowChargeRule handles EVs and ignores every other Vehicle. A fuel rule for
petrol cars would be one more subclass, added to the list in wiring.py.
"""
from abc import ABC, abstractmethod

from car_rental import Vehicle

from .config import EvConfig
from .models import ElectricVehicle, InspectionReport, PriceLine


class ReturnRule(ABC):
    @abstractmethod
    def charges(self, vehicle: Vehicle, report: InspectionReport) -> list[PriceLine]:
        ...


class LowChargeRule(ReturnRule):
    """EVs only: below the return threshold, pay per missing percentage point."""

    def __init__(self, config: EvConfig):
        self._config = config

    def charges(self, vehicle: Vehicle, report: InspectionReport) -> list[PriceLine]:
        if not isinstance(vehicle, ElectricVehicle):
            return []
        if report.charge_pct is None:
            raise ValueError(f"{vehicle.vehicle_id} is electric: report needs charge_pct")
        if not 0 <= report.charge_pct <= 100:
            raise ValueError("charge_pct must be within 0..100")
        shortfall = self._config.min_return_charge_pct - report.charge_pct
        if shortfall <= 0:
            return []
        fee = round(shortfall * self._config.recharge_fee_per_pct, 2)
        return [PriceLine(f"recharge ({report.charge_pct}% < "
                          f"{self._config.min_return_charge_pct}%)", fee)]
