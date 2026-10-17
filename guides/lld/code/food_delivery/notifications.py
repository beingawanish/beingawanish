"""Notifications through observers.

The service publishes OrderEvents; observers (push, SMS, the restaurant
tablet, analytics) subscribe. The service never knows who is listening.
A failing observer is logged and skipped: a broken SMS gateway must not
roll back a delivered order.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .status import OrderStatus

log = logging.getLogger(__name__)


class EventKind(Enum):
    STATUS_CHANGED = "status_changed"
    PARTNER_OFFERED = "partner_offered"
    PARTNER_ASSIGNED = "partner_assigned"
    DISPATCH_WAITING = "dispatch_waiting"
    DISPATCH_FAILED = "dispatch_failed"


@dataclass(frozen=True)
class OrderEvent:
    kind: EventKind
    order_id: str
    customer_id: str
    status: OrderStatus
    at: datetime
    detail: str = ""


class OrderObserver(ABC):
    @abstractmethod
    def on_event(self, event: OrderEvent) -> None:
        ...


class LoggingObserver(OrderObserver):
    def on_event(self, event: OrderEvent) -> None:
        log.info("%s %s %s %s", event.order_id, event.kind.value,
                 event.status.name, event.detail)


class RecordingObserver(OrderObserver):
    """Keeps every event. Handy in tests and demos."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[OrderEvent] = []

    def on_event(self, event: OrderEvent) -> None:
        with self._lock:
            self._events.append(event)

    @property
    def events(self) -> list[OrderEvent]:
        with self._lock:
            return list(self._events)


class Notifier:
    def __init__(self, observers: Iterable[OrderObserver] = ()):
        self._lock = threading.Lock()          # guards _observers
        self._observers: list[OrderObserver] = list(observers)

    def subscribe(self, observer: OrderObserver) -> None:
        with self._lock:
            self._observers.append(observer)

    def publish(self, events: Iterable[OrderEvent]) -> None:
        with self._lock:
            observers = list(self._observers)
        for event in events:
            for observer in observers:
                try:
                    observer.on_event(event)
                except Exception:
                    # Isolation boundary: one bad observer must not stop the
                    # others or the order flow. Logged with the traceback.
                    log.exception("observer %r failed on %s",
                                  observer, event.kind.value)
