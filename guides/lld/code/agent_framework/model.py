"""The model seam. The loop talks to `Model`; a real provider adapter and the
scripted fake both implement it. Nothing in this package imports an SDK."""
import copy
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from agent_framework.errors import ModelError
from agent_framework.messages import (Message, ModelResponse, StopReason, TextBlock,
                                      ToolUseBlock, Usage)


@dataclass(frozen=True)
class ModelRequest:
    """One call's worth of input, recorded by the fake so tests can inspect it."""
    system: str
    messages: list[Message]
    tools: list[dict[str, Any]]


class Model(ABC):
    @abstractmethod
    def complete(self, system: str, messages: list[Message],
                 tools: list[dict[str, Any]]) -> ModelResponse:
        """One model turn. Raise ModelError on transport or protocol failure."""


class ScriptedModel(Model):
    """Replays canned responses in order and records every request."""

    def __init__(self, responses: Iterable[ModelResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[ModelRequest] = []
        self._lock = threading.Lock()  # guards _responses and requests

    def complete(self, system: str, messages: list[Message],
                 tools: list[dict[str, Any]]) -> ModelResponse:
        with self._lock:
            self.requests.append(ModelRequest(system, list(messages), copy.deepcopy(tools)))
            if not self._responses:
                raise ModelError("script exhausted: the loop asked for more turns than scripted")
            return self._responses.pop(0)


def say(text: str, usage: Usage = Usage(10, 10)) -> ModelResponse:
    """A final answer."""
    return ModelResponse((TextBlock(text),), StopReason.END_TURN, usage)


def call(*uses: ToolUseBlock, text: str = "", usage: Usage = Usage(10, 10)) -> ModelResponse:
    """A turn that requests one or more tools (several = parallel tool use)."""
    blocks: tuple[TextBlock | ToolUseBlock, ...] = ((TextBlock(text),) if text else ()) + uses
    return ModelResponse(blocks, StopReason.TOOL_USE, usage)
