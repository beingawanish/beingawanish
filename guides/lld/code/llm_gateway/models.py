"""The unified request and response types every team codes against.

Provider adapters translate to and from their own wire formats; nothing
outside providers.py ever sees a provider-specific field name.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .errors import InvalidGatewayRequestError

ROLES = ("user", "assistant")


class StopReason(Enum):
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    REFUSAL = "refusal"


@dataclass(frozen=True)
class Message:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise InvalidGatewayRequestError(f"role must be one of {ROLES}, got {self.role!r}")
        if not self.content.strip():
            raise InvalidGatewayRequestError("message content must not be blank")


@dataclass(frozen=True)
class ChatRequest:
    """Exactly one of `model` (a route alias such as "smart") or `task`
    (such as "summarise") picks the route."""

    team: str
    messages: tuple[Message, ...]
    model: str | None = None
    task: str | None = None
    system: str = ""
    max_tokens: int = 1024
    temperature: float = 0.0

    def __post_init__(self) -> None:
        if not self.team.strip():
            raise InvalidGatewayRequestError("team must not be blank")
        if not self.messages:
            raise InvalidGatewayRequestError("at least one message is required")
        if self.messages[-1].role != "user":
            raise InvalidGatewayRequestError("the last message must come from the user")
        if (self.model is None) == (self.task is None):
            raise InvalidGatewayRequestError("set exactly one of model or task")
        if self.max_tokens <= 0:
            raise InvalidGatewayRequestError("max_tokens must be positive")
        if not 0.0 <= self.temperature <= 1.0:
            raise InvalidGatewayRequestError("temperature must be within [0, 1]")

    def prompt_text(self) -> str:
        """All the text the model will read: system prompt plus every message."""
        return "\n".join([self.system, *(m.content for m in self.messages)])


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class ProviderResult:
    """What a provider adapter returns: text, usage, why it stopped."""

    text: str
    usage: Usage
    stop_reason: StopReason


@dataclass(frozen=True)
class ChatResponse:
    request_id: str
    text: str
    provider: str
    model: str
    usage: Usage
    stop_reason: StopReason
    cost_usd: Decimal
    cached: bool = False
    fallbacks: tuple[str, ...] = field(default=())
