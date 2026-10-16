"""Find drivers near a point without scanning every driver in the city.

GridIndex buckets drivers into square cells. A radius query visits only the
cells that the search circle can touch, then checks exact distances.
"""
import math
import threading
from abc import ABC, abstractmethod

from .errors import InvalidInputError
from .models import Location

Cell = tuple[int, int]


class SpatialIndex(ABC):
    @abstractmethod
    def upsert(self, driver_id: str, location: Location) -> None:
        """Insert the driver, or move them if already indexed."""

    @abstractmethod
    def remove(self, driver_id: str) -> None:
        """Forget the driver. Unknown ids are ignored."""

    @abstractmethod
    def within(self, center: Location, radius_km: float) -> list[tuple[str, float]]:
        """(driver_id, distance_km) pairs inside the radius, nearest first."""


class GridIndex(SpatialIndex):
    """Uniform grid. One lock guards both maps, so a driver is never in two
    cells at once even while location pings and searches run in parallel."""

    def __init__(self, cell_km: float) -> None:
        if cell_km <= 0:
            raise InvalidInputError("cell_km must be positive")
        self._cell_km = cell_km
        self._cells: dict[Cell, set[str]] = {}
        self._where: dict[str, tuple[Cell, Location]] = {}
        self._lock = threading.Lock()

    def cell_of(self, location: Location) -> Cell:
        return (math.floor(location.x_km / self._cell_km),
                math.floor(location.y_km / self._cell_km))

    def upsert(self, driver_id: str, location: Location) -> None:
        cell = self.cell_of(location)
        with self._lock:
            self._detach(driver_id)
            self._cells.setdefault(cell, set()).add(driver_id)
            self._where[driver_id] = (cell, location)

    def remove(self, driver_id: str) -> None:
        with self._lock:
            self._detach(driver_id)

    def within(self, center: Location, radius_km: float) -> list[tuple[str, float]]:
        if radius_km < 0:
            raise InvalidInputError("radius_km must not be negative")
        cx, cy = self.cell_of(center)
        span = math.ceil(radius_km / self._cell_km)
        found: list[tuple[str, float]] = []
        with self._lock:
            for gx in range(cx - span, cx + span + 1):
                for gy in range(cy - span, cy + span + 1):
                    for driver_id in self._cells.get((gx, gy), ()):
                        distance = center.distance_to(self._where[driver_id][1])
                        if distance <= radius_km:
                            found.append((driver_id, distance))
        found.sort(key=lambda pair: (pair[1], pair[0]))
        return found

    def _detach(self, driver_id: str) -> None:
        """Caller holds self._lock."""
        entry = self._where.pop(driver_id, None)
        if entry is None:
            return
        bucket = self._cells[entry[0]]
        bucket.discard(driver_id)
        if not bucket:
            del self._cells[entry[0]]
