"""Append-only audit trail. Every change to money gets one entry, forever."""
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class AuditAction(Enum):
    USER_REGISTERED = "user_registered"
    GROUP_CREATED = "group_created"
    MEMBER_ADDED = "member_added"
    EXPENSE_ADDED = "expense_added"
    EXPENSE_DELETED = "expense_deleted"
    SETTLEMENT_RECORDED = "settlement_recorded"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    at: datetime
    actor: str
    action: AuditAction
    subject_id: str
    detail: str

    def __str__(self) -> str:
        return f"#{self.seq} {self.at:%H:%M} {self.actor} {self.action.value} {self.subject_id}: {self.detail}"


class AuditLog(ABC):
    """Append and read. There is deliberately no update and no delete."""

    @abstractmethod
    def append(self, at: datetime, actor: str, action: AuditAction, subject_id: str, detail: str) -> AuditEntry: ...

    @abstractmethod
    def entries(self, subject_id: str | None = None) -> tuple[AuditEntry, ...]: ...


class InMemoryAuditLog(AuditLog):
    """The lock guards _entries and keeps seq numbers gap-free and ordered."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[AuditEntry] = []

    def append(self, at: datetime, actor: str, action: AuditAction, subject_id: str, detail: str) -> AuditEntry:
        with self._lock:
            entry = AuditEntry(len(self._entries) + 1, at, actor, action, subject_id, detail)
            self._entries.append(entry)
            return entry

    def entries(self, subject_id: str | None = None) -> tuple[AuditEntry, ...]:
        with self._lock:
            return tuple(e for e in self._entries if subject_id is None or e.subject_id == subject_id)
