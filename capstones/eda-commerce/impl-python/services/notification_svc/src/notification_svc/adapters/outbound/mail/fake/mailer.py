"""The fake mail gateway: an outbound adapter behind the :class:`Mailer` port. It keeps the messages
in memory (the "fake mail outbox" of the Day 7 acceptance) and, like a real provider, dedupes on the
idempotency key."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from edacommon.ids import new_id

from notification_svc.application.ports import Email


@dataclass
class FakeMailer:
    outbox: list[Email] = field(default_factory=list)
    _ids: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    duplicates_suppressed: int = 0

    def send(self, email: Email, *, idempotency_key: str) -> str:
        with self._lock:
            if idempotency_key in self._ids:
                self.duplicates_suppressed += 1
                return self._ids[idempotency_key]
            message_id = f"msg_{new_id()}"
            self._ids[idempotency_key] = message_id
            self.outbox.append(email)
            return message_id
