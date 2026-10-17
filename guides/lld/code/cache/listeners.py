"""Removal notifications: who left the cache, and why.

A listener hears about every removal, with its cause. Use it to write dirty
entries back, release resources, or feed metrics. Listeners run *after* the
cache releases its lock, so a slow listener never blocks other readers.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class RemovalCause(Enum):
    CAPACITY = "capacity"   # evicted by the policy to make room
    EXPIRED = "expired"     # TTL ran out (found lazily or by the sweeper)
    EXPLICIT = "explicit"   # delete() or clear()
    REPLACED = "replaced"   # put() overwrote the key


@dataclass(frozen=True)
class RemovalNotification[K, V]:
    key: K
    value: V
    cause: RemovalCause


class EvictionListener[K, V](ABC):
    @abstractmethod
    def on_removal(self, notification: RemovalNotification[K, V]) -> None: ...


class LoggingListener[K, V](EvictionListener[K, V]):
    """Logs every removal at DEBUG. Handy as a default while debugging."""

    def on_removal(self, notification: RemovalNotification[K, V]) -> None:
        log.debug("removed %r (%s)", notification.key, notification.cause.value)
