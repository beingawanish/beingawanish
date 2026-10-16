"""The provider seam. A real adapter wraps one vendor SDK and maps its errors
onto the gateway's ProviderError family (429 -> ProviderRateLimitError,
529 -> ProviderOverloadedError, and so on). FakeProvider is deterministic,
offline, and lets a test script failures and latency."""
import math
import threading
from abc import ABC, abstractmethod
from collections import deque

from .clock import Clock
from .errors import ProviderError, ProviderTimeoutError
from .models import ChatRequest, ProviderResult, StopReason, Usage


class ModelProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, model: str, request: ChatRequest, timeout_s: float) -> ProviderResult:
        """Run one completion, or raise a ProviderError subclass."""


class FakeProvider(ModelProvider):
    """Replies "<model> says: <last user message>". Usage is one token per
    four characters, so tests can predict every number. The lock guards the
    failure script and the call log."""

    CHARS_PER_TOKEN = 4

    def __init__(self, name: str, clock: Clock, latency_s: float = 0.0) -> None:
        self.name = name
        self._clock = clock
        self._latency_s = latency_s
        self._script: deque[ProviderError] = deque()
        self._calls: list[str] = []
        self._lock = threading.Lock()

    def fail_next(self, *errors: ProviderError) -> None:
        with self._lock:
            self._script.extend(errors)

    def set_latency(self, seconds: float) -> None:
        with self._lock:
            self._latency_s = seconds

    @property
    def calls(self) -> list[str]:
        with self._lock:
            return list(self._calls)

    def complete(self, model: str, request: ChatRequest, timeout_s: float) -> ProviderResult:
        with self._lock:
            self._calls.append(model)
            scripted = self._script.popleft() if self._script else None
            latency = self._latency_s
        if latency > timeout_s:
            self._clock.sleep(timeout_s)
            raise ProviderTimeoutError(f"{self.name}/{model} took longer than {timeout_s}s")
        self._clock.sleep(latency)
        if scripted is not None:
            raise scripted
        return self._reply(model, request)

    def _reply(self, model: str, request: ChatRequest) -> ProviderResult:
        text = f"{model} says: {request.messages[-1].content}"
        output_tokens = math.ceil(len(text) / self.CHARS_PER_TOKEN)
        stop = StopReason.END_TURN
        if output_tokens > request.max_tokens:
            text = text[: request.max_tokens * self.CHARS_PER_TOKEN]
            output_tokens = request.max_tokens
            stop = StopReason.MAX_TOKENS
        input_tokens = math.ceil(len(request.prompt_text()) / self.CHARS_PER_TOKEN)
        return ProviderResult(text, Usage(input_tokens, output_tokens), stop)
