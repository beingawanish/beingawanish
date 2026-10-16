"""Telemetry events and the bus that carries them (Observer).

Controllers publish; the TrafficManagementCenter, dashboards and tests
subscribe. Publishers never know who is listening.
"""
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .models import ControlMode, GreenSplit, Phase

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelemetryEvent:
    intersection_id: str
    at: int


@dataclass(frozen=True)
class PhaseChanged(TelemetryEvent):
    phase: Phase


@dataclass(frozen=True)
class ModeChanged(TelemetryEvent):
    mode: ControlMode
    reason: str


@dataclass(frozen=True)
class CycleStarted(TelemetryEvent):
    split: GreenSplit
    queue_ns: int
    queue_ew: int


class TelemetryListener(ABC):
    @abstractmethod
    def on_event(self, event: TelemetryEvent) -> None:
        """Called synchronously on the publisher's thread. Keep it short and
        never call back into a controller from here."""


class TelemetrySink(ABC):
    """Where a controller sends its events. The controller knows nothing more."""

    @abstractmethod
    def send(self, event: TelemetryEvent) -> None:
        ...


class EventBus(TelemetrySink):
    """Fan-out to every subscriber. A failing listener is logged, not fatal."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # guards _listeners
        self._listeners: list[TelemetryListener] = []

    def subscribe(self, listener: TelemetryListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def send(self, event: TelemetryEvent) -> None:
        with self._lock:
            listeners = list(self._listeners)  # deliver outside the lock
        for listener in listeners:
            try:
                listener.on_event(event)
            except Exception:  # one bad dashboard must not stop the signals
                log.exception("listener %r failed on %r", listener, event)


class RecordingListener(TelemetryListener):
    """Keeps every event it sees. Handy in demos and tests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()  # guards _events
        self._events: list[TelemetryEvent] = []

    def on_event(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self) -> list[TelemetryEvent]:
        with self._lock:
            return list(self._events)
