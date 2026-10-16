"""Exact-match response cache, keyed on a normalised request.

Normalising means: collapse runs of whitespace and trim each text field, so
"Hi  there " and "Hi there" share a key. Case is kept, because case can
change the answer. The key also includes the team (no cross-team leaks) and
the resolved route alias. Only temperature-0 requests are cached; sampling
at a higher temperature asks for variety, and a cache would hide it.
"""
import hashlib
import json
import threading
from collections import OrderedDict

from .clock import Clock
from .config import CacheConfig
from .models import ChatRequest, ChatResponse


def _normalise(text: str) -> str:
    return " ".join(text.split())


def fingerprint(request: ChatRequest, alias: str) -> str:
    """Stable SHA-256 of the normalised request. Also used by the audit log."""
    payload = {
        "team": request.team,
        "alias": alias,
        "system": _normalise(request.system),
        "messages": [[m.role, _normalise(m.content)] for m in request.messages],
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class ResponseCache:
    """TTL plus LRU eviction. The lock guards the OrderedDict."""

    def __init__(self, config: CacheConfig, clock: Clock) -> None:
        self._config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, ChatResponse]] = OrderedDict()

    @staticmethod
    def cacheable(request: ChatRequest) -> bool:
        return request.temperature == 0.0

    def get(self, key: str) -> ChatResponse | None:
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            stored_at, response = hit
            if self._clock.now() - stored_at >= self._config.ttl_s:
                del self._entries[key]
                return None
            self._entries.move_to_end(key)
            return response

    def put(self, key: str, response: ChatResponse) -> None:
        with self._lock:
            self._entries[key] = (self._clock.now(), response)
            self._entries.move_to_end(key)
            while len(self._entries) > self._config.max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
