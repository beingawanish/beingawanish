"""Configuration: every tunable the cache has, in one validated place.

No method in the package contains a literal capacity, TTL or interval. Change
a number here and the behaviour follows; a bad number fails at construction,
not three hours into production.
"""
from dataclasses import dataclass
from enum import Enum

from .errors import CacheConfigError


class EvictionKind(Enum):
    LRU = "lru"
    LFU = "lfu"
    FIFO = "fifo"


@dataclass(frozen=True)
class CacheConfig:
    max_entries: int = 1024            # capacity by count
    max_size: int | None = None        # capacity by size units; None = count only
    default_ttl: float | None = None   # seconds; None = entries never expire
    eviction: EvictionKind = EvictionKind.LRU
    sweep_interval: float = 30.0       # seconds between background sweeps

    def __post_init__(self) -> None:
        if self.max_entries < 1:
            raise CacheConfigError(f"max_entries must be >= 1, got {self.max_entries}")
        if self.max_size is not None and self.max_size < 1:
            raise CacheConfigError(f"max_size must be >= 1, got {self.max_size}")
        if self.default_ttl is not None and self.default_ttl <= 0:
            raise CacheConfigError(f"default_ttl must be > 0, got {self.default_ttl}")
        if self.sweep_interval <= 0:
            raise CacheConfigError(
                f"sweep_interval must be > 0, got {self.sweep_interval}")
