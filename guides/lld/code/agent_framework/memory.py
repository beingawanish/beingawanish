"""Conversation memory: the full transcript, plus a truncated window to send.

The transcript is append-only. window() builds what fits the token budget:
  * the first user message (the task) is always kept,
  * after it, messages go in (assistant, user) pairs, so a tool_result is
    never separated from the tool_use that asked for it,
  * the oldest pairs drop first; the newest pair is always kept,
  * a note on the task message says how many messages were dropped.
"""
import json
import threading
from abc import ABC, abstractmethod

from agent_framework.config import AgentConfig
from agent_framework.errors import ConversationError
from agent_framework.messages import Message, Role, TextBlock


class TokenCounter(ABC):
    @abstractmethod
    def count(self, message: Message) -> int: ...


class CharEstimateCounter(TokenCounter):
    """Characters / chars_per_token. Good enough to decide what to drop;
    the token budget itself uses the counts the model reports."""

    def __init__(self, config: AgentConfig) -> None:
        self._chars_per_token = config.chars_per_token

    def count(self, message: Message) -> int:
        chars = len(json.dumps(message.to_dict()))
        return -(-chars // self._chars_per_token)  # ceiling division


class ConversationMemory:
    def __init__(self, config: AgentConfig, counter: TokenCounter) -> None:
        self._budget = config.memory_token_budget
        self._counter = counter
        self._messages: list[Message] = []
        self._lock = threading.Lock()  # guards _messages

    def append(self, message: Message) -> None:
        """Two user messages in a row merge into one (a new task after a run
        that stopped on tool results). Two assistant messages are a bug."""
        with self._lock:
            if not self._messages and message.role is not Role.USER:
                raise ConversationError("a conversation must start with a user message")
            last = self._messages[-1] if self._messages else None
            if last and last.role is message.role:
                if message.role is Role.ASSISTANT:
                    raise ConversationError("two assistant messages in a row")
                self._messages[-1] = Message(Role.USER, last.content + message.content)
                return
            self._messages.append(message)

    def transcript(self) -> list[Message]:
        with self._lock:
            return list(self._messages)

    def window(self) -> list[Message]:
        with self._lock:
            messages = list(self._messages)
        if not messages:
            return []
        task, rest = messages[0], messages[1:]
        # rest alternates assistant, user, ... so pairing from the front keeps
        # each tool_use with its tool_result. Only the last unit can be a single.
        units = [rest[i:i + 2] for i in range(0, len(rest), 2)]
        kept = units[-1:]  # the newest unit always goes, even over budget
        used = sum(self._counter.count(m) for m in [task, *(units[-1] if units else [])])
        for unit in reversed(units[:-1]):
            cost = sum(self._counter.count(m) for m in unit)
            if used + cost > self._budget:
                break
            kept.insert(0, unit)
            used += cost
        dropped = len(rest) - sum(len(u) for u in kept)
        if dropped:
            note = TextBlock(f"[{dropped} earlier messages were truncated to fit the context budget]")
            task = Message(task.role, task.content + (note,))
        return [task] + [m for unit in kept for m in unit]
