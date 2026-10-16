"""Hooks: middleware around every tool call.

before() can veto a call by returning a reason. after() sees the result and
may replace it. The executor runs before() hooks in order and after() hooks
in reverse, like nested middleware.
"""
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from agent_framework.clock import Clock
from agent_framework.messages import ToolResultBlock, ToolUseBlock

log = logging.getLogger(__name__)


class ToolHook:
    """Base hook: both methods are no-ops, so a subclass overrides only what it needs."""

    def before(self, call: ToolUseBlock) -> str | None:
        """Return a reason string to block the call, or None to let it through."""
        return None

    def after(self, call: ToolUseBlock, result: ToolResultBlock) -> ToolResultBlock:
        return result


class LoggingHook(ToolHook):
    """Logs every call with its duration. Calls overlap in time, so start
    times are keyed by tool_use id and guarded by a lock."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._started: dict[str, float] = {}
        self._lock = threading.Lock()  # guards _started

    def before(self, call: ToolUseBlock) -> str | None:
        with self._lock:
            self._started[call.id] = self._clock.now()
        log.info("tool start %s %s", call.name, call.id)
        return None

    def after(self, call: ToolUseBlock, result: ToolResultBlock) -> ToolResultBlock:
        with self._lock:
            started = self._started.pop(call.id, self._clock.now())
        log.info("tool end %s %s error=%s %.3fs", call.name, call.id,
                 result.is_error, self._clock.now() - started)
        return result


ArgumentRule = Callable[[dict[str, Any]], str | None]


class ArgumentPolicyHook(ToolHook):
    """Per-tool argument rules, e.g. "send_email only to our own domain".
    A rule returns a reason to block, or None."""

    def __init__(self, rules: Mapping[str, ArgumentRule]) -> None:
        self._rules = dict(rules)

    def before(self, call: ToolUseBlock) -> str | None:
        rule = self._rules.get(call.name)
        return rule(call.input) if rule else None
