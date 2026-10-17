"""Idempotency for side-effecting tools.

The key is (run_id, tool name, canonical input). Retry a crashed run with the
same run_id, or let the model repeat a call, and the email goes out once: the
second call gets the stored result back instead of running again.
"""
import json
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_framework.clock import Clock


def idempotency_key(run_id: str, tool_name: str, tool_input: dict[str, Any]) -> str:
    """sort_keys makes {"a":1,"b":2} and {"b":2,"a":1} the same key."""
    return f"{run_id}:{tool_name}:{json.dumps(tool_input, sort_keys=True, default=str)}"


@dataclass(frozen=True)
class StoredResult:
    output: str
    stored_at: float


class IdempotencyStore(ABC):
    @abstractmethod
    def run_once(self, key: str, action: Callable[[], str]) -> tuple[str, bool]:
        """Run action unless key already holds a live result.
        Returns (output, replayed). A raised action stores nothing."""


class InMemoryIdempotencyStore(IdempotencyStore):
    """Results expire after ttl_seconds. One lock per key, so two parallel
    identical calls cannot both run; different keys never wait on each other."""

    def __init__(self, clock: Clock, ttl_seconds: float) -> None:
        self._clock = clock
        self._ttl = ttl_seconds
        self._results: dict[str, StoredResult] = {}
        self._key_locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()  # guards _results and _key_locks

    def _live(self, key: str) -> StoredResult | None:
        with self._lock:
            stored = self._results.get(key)
            if stored and self._clock.now() - stored.stored_at >= self._ttl:
                del self._results[key]
                return None
            return stored

    def run_once(self, key: str, action: Callable[[], str]) -> tuple[str, bool]:
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            stored = self._live(key)
            if stored:
                return stored.output, True
            output = action()
            with self._lock:
                self._results[key] = StoredResult(output, self._clock.now())
            return output, False
