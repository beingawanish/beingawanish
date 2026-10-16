"""Post-return inspection: what is new damage, and what does it cost?

DamageInspector keeps a ledger of the damage each car already carries, so a
customer pays only for what is new. assess() is pure: it prices the report
and changes nothing. record() commits the new damage once the money side has
succeeded. That split is what makes a retried inspection safe.
"""
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from .config import InspectionConfig
from .models import Damage, InspectionReport, PriceLine


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
