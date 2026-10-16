"""The message vocabulary: roles, content blocks, stop reasons, usage.

The names follow the Claude Messages API (text, tool_use, tool_result,
stop_reason, input_tokens/output_tokens) so an adapter is a thin mapping.
Nothing here imports a provider SDK.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(Enum):
    USER = "user"
    ASSISTANT = "assistant"


class StopReason(Enum):
    END_TURN = "end_turn"      # the model is done
    TOOL_USE = "tool_use"      # the model wants tools run
    MAX_TOKENS = "max_tokens"  # output was cut off; tool inputs may be incomplete
    REFUSAL = "refusal"        # the model declined


@dataclass(frozen=True)
class TextBlock:
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass(frozen=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"type": "tool_result", "tool_use_id": self.tool_use_id,
                "content": self.content, "is_error": self.is_error}


Block = TextBlock | ToolUseBlock | ToolResultBlock


@dataclass(frozen=True)
class Message:
    role: Role
    content: tuple[Block, ...]

    @classmethod
    def user_text(cls, text: str) -> "Message":
        return cls(Role.USER, (TextBlock(text),))

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def text(self) -> str:
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role.value, "content": [b.to_dict() for b in self.content]}


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens,
                     self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class ModelResponse:
    content: tuple[Block, ...]
    stop_reason: StopReason
    usage: Usage = field(default_factory=Usage)

    def as_message(self) -> Message:
        return Message(Role.ASSISTANT, self.content)
