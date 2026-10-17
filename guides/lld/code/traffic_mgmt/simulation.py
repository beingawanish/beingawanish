"""The deterministic world loop: one second at a time, in a fixed order.

Each second: advance the clock, step every controller (sorted by id),
then step the centre. Same inputs, same outputs, every run.
"""
import threading
from collections.abc import Mapping

from .clock import ManualClock
from .controller import IntersectionController
from .errors import UnknownIntersectionError
from .models import Axis
from .sensors import ApproachQueues
from .tmc import TrafficManagementCenter


class TrafficSimulation:
    def __init__(
        self,
        clock: ManualClock,
        tmc: TrafficManagementCenter,
        controllers: Mapping[str, IntersectionController],
        queues: Mapping[str, ApproachQueues],
    ) -> None:
        self._clock = clock
        self._tmc = tmc
        self._controllers = dict(sorted(controllers.items()))
        self._queues = dict(queues)
        self._lock = threading.Lock()  # one world step at a time

    def add_arrivals(self, intersection_id: str, axis: Axis, vehicles: int) -> None:
        try:
            queues = self._queues[intersection_id]
        except KeyError:
            raise UnknownIntersectionError(intersection_id) from None
        queues.arrive(axis, vehicles)

    def run(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("seconds must be >= 0")
        for _ in range(seconds):
            with self._lock:
                self._clock.advance(1)
                for controller in self._controllers.values():
                    controller.step()
                self._tmc.step()
