"""The radio/fibre link between the centre and each controller.

CommsNetwork answers one question: is this controller reachable right now?
InMemoryComms lets tests and demos cut and restore links on purpose.

Uplink is a controller's outbound telemetry path. While the link is down it
stores events in a bounded buffer (oldest dropped first) and forwards them,
in order, as soon as the link is back. Store-and-forward, so the centre
learns what happened during the outage instead of a blank.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections import deque

from .events import TelemetryEvent, TelemetrySink

log = logging.getLogger(__name__)


class CommsNetwork(ABC):
    @abstractmethod
    def is_up(self, intersection_id: str) -> bool:
        ...


class InMemoryComms(CommsNetwork):
    def __init__(self) -> None:
        self._lock = threading.Lock()  # guards _down
        self._down: set[str] = set()

    def is_up(self, intersection_id: str) -> bool:
        with self._lock:
            return intersection_id not in self._down

    def sever(self, intersection_id: str) -> None:
        with self._lock:
            self._down.add(intersection_id)
        log.warning("comms to %s severed", intersection_id)

    def restore(self, intersection_id: str) -> None:
        with self._lock:
            self._down.discard(intersection_id)
        log.info("comms to %s restored", intersection_id)


class Uplink(TelemetrySink):
    """Store-and-forward telemetry for one controller."""

    def __init__(
        self,
        intersection_id: str,
        comms: CommsNetwork,
        downstream: TelemetrySink,
        capacity: int,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._id = intersection_id
        self._comms = comms
        self._downstream = downstream
        self._lock = threading.Lock()  # guards _buffer and _dropped; held while forwarding
        self._buffer: deque[TelemetryEvent] = deque(maxlen=capacity)
        self._dropped = 0

    def send(self, event: TelemetryEvent) -> None:
        with self._lock:
            if not self._comms.is_up(self._id):
                if len(self._buffer) == self._buffer.maxlen:
                    self._dropped += 1
                self._buffer.append(event)
                return
            # Held while forwarding so two threads cannot reorder the stream.
            while self._buffer:
                self._downstream.send(self._buffer.popleft())
            self._downstream.send(event)

    @property
    def buffered(self) -> int:
        with self._lock:
            return len(self._buffer)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped
