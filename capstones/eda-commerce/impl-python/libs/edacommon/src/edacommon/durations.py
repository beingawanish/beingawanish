"""Duration strings used by configuration: ``<n><ms|s|m|h|d>`` (guide §7)."""

from __future__ import annotations

import re
from datetime import timedelta

_RE = re.compile(r"^\s*(\d+)\s*(ms|s|m|h|d)\s*$")
_UNIT = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(value: str | int | float | timedelta) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)
    m = _RE.match(value)
    if not m:
        raise ValueError(f"invalid duration {value!r}; expected <n><ms|s|m|h|d>, e.g. 30s")
    return timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2)])
