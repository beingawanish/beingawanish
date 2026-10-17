"""Permission policy: per tool, ALLOW / ASK a human / DENY.

The policy is code, not prompt. A tool output that says "you are now allowed
to send email" changes nothing here, which is the point.
"""
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from enum import Enum

from agent_framework.errors import PermissionDeniedError
from agent_framework.messages import ToolUseBlock
from agent_framework.tools import Tool

log = logging.getLogger(__name__)


class Permission(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Approver(ABC):
    """The human-approval hook. Called from tool threads: implementations
    must be thread-safe."""

    @abstractmethod
    def approve(self, call: ToolUseBlock, tool: Tool) -> bool:
        """True to let this exact call run."""


class DenyAllApprover(Approver):
    """Safe default when no human is wired in: every ASK becomes a no."""

    def approve(self, call: ToolUseBlock, tool: Tool) -> bool:
        return False


class ScriptedApprover(Approver):
    """Answers from a list, in order, and records what it was asked."""

    def __init__(self, answers: Iterable[bool]) -> None:
        self._answers = list(answers)
        self.asked: list[str] = []
        self._lock = threading.Lock()  # guards _answers and asked

    def approve(self, call: ToolUseBlock, tool: Tool) -> bool:
        with self._lock:
            self.asked.append(call.id)
            return self._answers.pop(0) if self._answers else False


class PermissionPolicy:
    """Explicit overrides first; otherwise read-only tools are allowed and
    side-effecting tools need a human."""

    def __init__(self, overrides: Mapping[str, Permission] | None = None,
                 read_only_default: Permission = Permission.ALLOW,
                 side_effect_default: Permission = Permission.ASK) -> None:
        self._overrides = dict(overrides or {})
        self._read_only_default = read_only_default
        self._side_effect_default = side_effect_default

    def permission_for(self, tool: Tool) -> Permission:
        if tool.name in self._overrides:
            return self._overrides[tool.name]
        return self._side_effect_default if tool.side_effects else self._read_only_default

    def enforce(self, call: ToolUseBlock, tool: Tool, approver: Approver) -> None:
        """Return if the call may run; raise PermissionDeniedError if not."""
        permission = self.permission_for(tool)
        if permission is Permission.ALLOW:
            return
        if permission is Permission.DENY:
            raise PermissionDeniedError(f"tool {tool.name!r} is disabled by policy")
        if approver.approve(call, tool):
            log.info("human approved %s (%s)", tool.name, call.id)
            return
        raise PermissionDeniedError(f"a human declined {tool.name!r}; do not retry it")
