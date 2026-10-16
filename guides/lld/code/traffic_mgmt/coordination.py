"""Green-wave design for a corridor of intersections.

Every signal on the corridor runs the same cycle length. Each one's
north-south green starts later than its upstream neighbour's by the travel
time between them. A car that leaves on green at design speed then meets
green at every downstream signal.
"""
from collections.abc import Sequence

from .config import SafetyTimings
from .errors import InvalidPlanError
from .models import Axis
from .network import RoadNetwork
from .timing import CoordinatedPlan


class GreenWaveDesigner:
    def __init__(self, network: RoadNetwork, safety: SafetyTimings) -> None:
        self._network = network
        self._safety = safety

    def design(
        self,
        link_ids: Sequence[str],
        speed_mps: float,
        cycle_length: int,
        ns_green: int,
    ) -> dict[str, CoordinatedPlan]:
        """One CoordinatedPlan per intersection, keyed by id, in corridor order."""
        if not link_ids:
            raise InvalidPlanError("a corridor needs at least one link")
        if speed_mps <= 0:
            raise InvalidPlanError("design speed must be positive")
        links = [self._network.link(link_id) for link_id in link_ids]
        for prev, nxt in zip(links, links[1:]):
            if prev.to_id != nxt.from_id:
                raise InvalidPlanError(f"{prev.link_id} does not lead into {nxt.link_id}")
        for link in links:
            if link.approach is not Axis.NS:
                raise InvalidPlanError(f"{link.link_id}: corridors run on the NS axis")
        offsets = {links[0].from_id: 0}
        for link in links:
            travel = round(link.length_m / speed_mps)
            offsets[link.to_id] = (offsets[link.from_id] + travel) % cycle_length
        return {
            iid: CoordinatedPlan(cycle_length, offset, ns_green, self._safety, f"wave@{offset}s")
            for iid, offset in offsets.items()
        }
