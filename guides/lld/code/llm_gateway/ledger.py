"""Token accounting and the cost ledger.

Cost comes from the usage the provider reported, never from our estimate,
and money is Decimal: a ledger that drifts by float rounding is a ledger
finance stops trusting. The lock guards the entry list.
"""
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .clock import Clock
from .config import ModelSpec
from .models import Usage

MTOK = Decimal(1_000_000)
MICRO_DOLLAR = Decimal("0.000001")


@dataclass(frozen=True)
class LedgerEntry:
    request_id: str
    team: str
    model_key: str
    usage: Usage
    cost_usd: Decimal
    at: float


class CostLedger:
    def __init__(self, models: Mapping[str, ModelSpec], clock: Clock) -> None:
        self._models = dict(models)
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: list[LedgerEntry] = []

    def price(self, model_key: str, usage: Usage) -> Decimal:
        spec = self._models[model_key]
        raw = (usage.input_tokens * spec.input_usd_per_mtok
               + usage.output_tokens * spec.output_usd_per_mtok) / MTOK
        return raw.quantize(MICRO_DOLLAR)

    def record(self, request_id: str, team: str, model_key: str, usage: Usage) -> LedgerEntry:
        entry = LedgerEntry(request_id, team, model_key, usage,
                            self.price(model_key, usage), self._clock.now())
        with self._lock:
            self._entries.append(entry)
        return entry

    def total_cost(self, team: str) -> Decimal:
        with self._lock:
            return sum((e.cost_usd for e in self._entries if e.team == team), Decimal("0"))

    def total_tokens(self, team: str) -> int:
        with self._lock:
            return sum(e.usage.total for e in self._entries if e.team == team)

    def entries(self) -> list[LedgerEntry]:
        with self._lock:
            return list(self._entries)
