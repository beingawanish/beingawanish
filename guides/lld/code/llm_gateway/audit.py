"""Audit records: who called what, what it cost, how it ended.

A record never holds prompt or response text. It holds a fingerprint (the
SHA-256 cache key) and a character count, which is enough to correlate
duplicate requests and spot oversized prompts without storing the content.
"""
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from decimal import Decimal

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditRecord:
    request_id: str
    team: str
    route: str
    outcome: str
    model_key: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_s: float = 0.0
    cached: bool = False
    fallbacks: int = 0
    error: str = ""
    prompt_fingerprint: str = ""
    prompt_chars: int = 0


class AuditLog(ABC):
    @abstractmethod
    def write(self, record: AuditRecord) -> None:
        ...


class InMemoryAuditLog(AuditLog):
    """Keeps records for tests and also emits each one as a log line.
    The lock guards the list."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        with self._lock:
            self._records.append(record)
        log.info("audit %s", asdict(record))

    def records(self) -> list[AuditRecord]:
        with self._lock:
            return list(self._records)
