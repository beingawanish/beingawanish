"""Post-return inspection: damage charges and return rules.

DamageInspector keeps a ledger of the damage each car already carries, so a
customer pays only for what is new. assess() is pure: it prices the report
and changes nothing. record() commits the new damage once the money side has
succeeded. That split is what makes a retried inspection safe.

ReturnRule is the seam for "charge something at return". LowChargeRule is the
EV rule; a fuel rule for petrol cars would be one more subclass.
"""
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass

from car_rental import Vehicle

from .config import EvConfig, InspectionConfig
from .models import Damage, ElectricVehicle, InspectionReport, PriceLine


@dataclass(frozen=True)
class DamageAssessment:
    new_damage: frozenset[Damage]
    lines: tuple[PriceLine, ...]
    needs_repair: bool


class DamageInspector:
    def __init__(self, config: InspectionConfig):
        self._config = config
        self._lock = threading.Lock()   # guards _known
        self._known: dict[str, set[Damage]] = {}

    def known(self, vehicle_id: str) -> frozenset[Damage]:
        with self._lock:
            return frozenset(self._known.get(vehicle_id, set()))

    def record(self, vehicle_id: str, damages: Iterable[Damage]) -> None:
        """Add damage to the car's ledger (pickup walk-around, or after billing)."""
        with self._lock:
            self._known.setdefault(vehicle_id, set()).update(damages)

    def assess(self, vehicle_id: str, report: InspectionReport) -> DamageAssessment:
        new = report.damages - self.known(vehicle_id)
        ordered = sorted(new, key=lambda d: (d.kind.value, d.panel))
        lines = tuple(
            PriceLine(f"damage: {d.kind.value} ({d.panel})",
                      self._config.damage_charges[d.kind])
            for d in ordered)
        needs_repair = any(d.kind in self._config.needs_repair
                           for d in self.known(vehicle_id) | new)
        return DamageAssessment(frozenset(new), lines, needs_repair)

    def repair(self, vehicle_id: str) -> None:
        """The workshop fixed everything that needed repair."""
        with self._lock:
            known = self._known.get(vehicle_id, set())
            self._known[vehicle_id] = {d for d in known
                                       if d.kind not in self._config.needs_repair}


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
