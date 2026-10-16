"""The road network: intersections joined by one-way links.

A Link runs from one intersection to the next and arrives at the downstream
intersection on one axis (its approach). Lane closures live here, so the
router and the incident handler read the same truth.
"""
import heapq
import threading
from dataclasses import dataclass
from fractions import Fraction

from .errors import NoRouteError, UnknownIntersectionError, UnknownLinkError
from .models import Axis


@dataclass(frozen=True)
class Link:
    link_id: str
    from_id: str
    to_id: str
    length_m: int
    approach: Axis  # the axis this traffic uses at to_id
    lanes: int = 2

    def __post_init__(self) -> None:
        if self.length_m <= 0 or self.lanes <= 0:
            raise ValueError(f"link {self.link_id}: length and lanes must be positive")
        if self.from_id == self.to_id:
            raise ValueError(f"link {self.link_id} loops onto itself")


class RoadNetwork:
    """Graph of intersections and links. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # guards the three collections below
        self._intersections: set[str] = set()
        self._links: dict[str, Link] = {}
        self._lanes_closed: dict[str, int] = {}

    def add_intersection(self, intersection_id: str) -> None:
        if not intersection_id:
            raise ValueError("intersection_id must be non-empty")
        with self._lock:
            self._intersections.add(intersection_id)

    def add_link(self, link: Link) -> None:
        with self._lock:
            for end in (link.from_id, link.to_id):
                if end not in self._intersections:
                    raise UnknownIntersectionError(end)
            if link.link_id in self._links:
                raise ValueError(f"duplicate link {link.link_id}")
            self._links[link.link_id] = link
            self._lanes_closed[link.link_id] = 0

    def link(self, link_id: str) -> Link:
        with self._lock:
            return self._get(link_id)

    def intersections(self) -> list[str]:
        with self._lock:
            return sorted(self._intersections)

    def set_lanes_closed(self, link_id: str, lanes_closed: int) -> Fraction:
        """Record an incident. Returns the share of capacity still open."""
        with self._lock:
            link = self._get(link_id)
            if not 0 <= lanes_closed <= link.lanes:
                raise ValueError(f"lanes_closed must be in [0, {link.lanes}]")
            self._lanes_closed[link_id] = lanes_closed
            return Fraction(link.lanes - lanes_closed, link.lanes)

    def is_open(self, link_id: str) -> bool:
        with self._lock:
            link = self._get(link_id)
            return self._lanes_closed[link_id] < link.lanes

    def shortest_route(self, origin: str, destination: str) -> list[Link]:
        """Dijkstra by length over open links. Ties break by link id."""
        with self._lock:
            for end in (origin, destination):
                if end not in self._intersections:
                    raise UnknownIntersectionError(end)
            outgoing: dict[str, list[Link]] = {}
            for link in sorted(self._links.values(), key=lambda lk: lk.link_id):
                if self._lanes_closed[link.link_id] < link.lanes:
                    outgoing.setdefault(link.from_id, []).append(link)
        best: dict[str, int] = {origin: 0}
        came_by: dict[str, Link] = {}
        frontier: list[tuple[int, str]] = [(0, origin)]
        while frontier:
            dist, node = heapq.heappop(frontier)
            if node == destination:
                break
            if dist > best[node]:
                continue
            for link in outgoing.get(node, []):
                candidate = dist + link.length_m
                if candidate < best.get(link.to_id, candidate + 1):
                    best[link.to_id] = candidate
                    came_by[link.to_id] = link
                    heapq.heappush(frontier, (candidate, link.to_id))
        if destination not in best:
            raise NoRouteError(f"no open route {origin} -> {destination}")
        route: list[Link] = []
        node = destination
        while node != origin:
            route.append(came_by[node])
            node = came_by[node].from_id
        return route[::-1]

    def _get(self, link_id: str) -> Link:
        try:
            return self._links[link_id]
        except KeyError:
            raise UnknownLinkError(link_id) from None
