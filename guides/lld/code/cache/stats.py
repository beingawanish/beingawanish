"""Hit/miss/eviction counters, and the frozen snapshot callers get to see.

The cache mutates a StatsCounter under its own lock. Callers only ever get a
CacheStats snapshot, so a dashboard reading stats can never see a half-updated
set of numbers or change them by accident.
"""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    puts: int = 0
    evictions: int = 0     # removed to make room (count or size)
    expirations: int = 0   # removed because the TTL ran out

    @property
    def requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0


@dataclass
class StatsCounter:
    """Mutable twin of CacheStats. Not thread-safe; the cache's lock guards it."""

    hits: int = 0
    misses: int = 0
    puts: int = 0
    evictions: int = 0
    expirations: int = 0

    def snapshot(self) -> CacheStats:
        return CacheStats(**asdict(self))
