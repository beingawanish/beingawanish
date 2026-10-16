"""Observer seam: the service announces what happened; observers decide
who hears about it (push notification, SMS, analytics, a test recorder)."""
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

log = logging.getLogger(__name__)


class EventKind(Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    OFFER_DECLINED = "OFFER_DECLINED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    MATCHED = "MATCHED"
    DRIVER_ARRIVING = "DRIVER_ARRIVING"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class TripEvent:
    kind: EventKind
    trip_id: str
    at: datetime
    driver_id: str | None = None
    detail: str = ""


class TripObserver(ABC):
    @abstractmethod
    def notify(self, event: TripEvent) -> None: ...


class EventPublisher:
    """Fans each event out to every subscriber.

    A failing observer is logged and skipped: a broken SMS gateway must never
    roll back a match. The lock guards the subscriber list only.
    """

    def __init__(self) -> None:
        self._observers: list[TripObserver] = []
        self._lock = threading.Lock()

    def subscribe(self, observer: TripObserver) -> None:
        with self._lock:
            self._observers.append(observer)

    def publish(self, event: TripEvent) -> None:
        with self._lock:
            observers = list(self._observers)
        for observer in observers:
            try:
                observer.notify(event)
            except Exception:  # isolate observers; never a bare except
                log.exception("observer %r failed on %s", observer, event.kind.value)


class RecordingObserver(TripObserver):
    """Keeps every event in order. Used by tests; handy in demos."""

    def __init__(self) -> None:
        self.events: list[TripEvent] = []
        self._lock = threading.Lock()

    def notify(self, event: TripEvent) -> None:
        with self._lock:
            self.events.append(event)

    def kinds(self, trip_id: str | None = None) -> list[EventKind]:
        with self._lock:
            return [e.kind for e in self.events
                    if trip_id is None or e.trip_id == trip_id]
