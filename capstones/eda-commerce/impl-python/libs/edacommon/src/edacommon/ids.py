"""UUIDv7 and the clock abstraction (guide §4 ``ids``, §6.2).

Python 3.13 has no ``uuid.uuid7``. This is RFC 9562 §5.7 with the optional monotonic counter of
§6.2 method 1 (12-bit ``rand_a`` used as a counter within the same millisecond), so ids minted in one
process sort in creation order even inside one millisecond. That property is what lets the polling
relay break ``created_at`` ties by ``id``.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7(now_ms: int | None = None) -> uuid.UUID:
    """Return a new UUIDv7. ``now_ms`` is for tests; production uses the wall clock."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000 if now_ms is None else now_ms
        if ms <= _last_ms:
            ms = _last_ms
            _counter += 1
            if _counter > 0xFFF:  # counter overflow: borrow the next millisecond
                ms += 1
                _counter = 0
        else:
            _counter = int.from_bytes(os.urandom(2), "big") & 0x7FF  # leave headroom for increments
        _last_ms = ms
        rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
        value = (ms & ((1 << 48) - 1)) << 80
        value |= 0x7 << 76
        value |= (_counter & 0xFFF) << 64
        value |= 0b10 << 62
        value |= rand_b
        return uuid.UUID(int=value)


def new_id() -> str:
    """UUIDv7 in canonical lower-case text form, the only id representation on the wire."""
    return str(uuid7())


def uuid7_time(u: uuid.UUID | str) -> datetime:
    value = uuid.UUID(str(u)).int
    return datetime.fromtimestamp((value >> 80) / 1000, tz=UTC)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """UTC wall clock. Only adapters and the runtime call it; the domain receives ``now``."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """A clock for tests: starts at a fixed instant and only moves when told to."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2026, 11, 18, 11, 6, 40, tzinfo=UTC)  # = contracts TS_EXAMPLE
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def advance(self, delta: timedelta | float) -> datetime:
        with self._lock:
            self._now += delta if isinstance(delta, timedelta) else timedelta(seconds=delta)
            return self._now

    def set(self, value: datetime) -> None:
        with self._lock:
            self._now = value


def to_millis(dt: datetime) -> int:
    if dt.tzinfo is None:
        raise ValueError("naive datetime; every time in this system is UTC-aware (guide §5 rule 7)")
    return int(dt.timestamp() * 1000)


def from_millis(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def rfc3339(dt: datetime) -> str:
    """RFC 3339 UTC with millisecond precision and ``Z`` (guide §5 rule 13)."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
