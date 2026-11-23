"""A broker-independent view of one consumed record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from edacommon.envelope import CE_ID, CE_TYPE, headers_to_dict


@dataclass(frozen=True, slots=True)
class ConsumedRecord:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None
    headers: list[tuple[str, bytes | None]] = field(default_factory=list)
    timestamp: datetime | None = None

    @classmethod
    def from_kafka(cls, msg: Any) -> ConsumedRecord:
        from edacommon.ids import from_millis

        ts_type, ts = msg.timestamp()
        return cls(
            topic=msg.topic(),
            partition=msg.partition(),
            offset=msg.offset(),
            key=msg.key(),
            value=msg.value(),
            headers=list(msg.headers() or []),
            timestamp=from_millis(ts) if ts_type and ts and ts > 0 else None,
        )

    @property
    def header_map(self) -> dict[str, str | None]:
        return headers_to_dict(self.headers)

    def header(self, name: str) -> str | None:
        return self.header_map.get(name)

    @property
    def event_type(self) -> str | None:
        return self.header(CE_TYPE)

    @property
    def event_id(self) -> str | None:
        return self.header(CE_ID)

    @property
    def key_str(self) -> str | None:
        return None if self.key is None else self.key.decode("utf-8", errors="replace")
