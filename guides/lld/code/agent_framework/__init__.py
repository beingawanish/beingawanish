"""Agent tool-calling runtime: tools, the loop, permissions, hooks, memory."""
import logging

from agent_framework.agent import Agent, AgentResult, RunStatus
from agent_framework.clock import Clock, FakeClock, SystemClock
from agent_framework.config import AgentConfig
from agent_framework.errors import (AgentError, ConfigError, ConversationError, ModelError,
                                    PermissionDeniedError, SchemaError, ToolError,
                                    ToolExecutionError, ToolInputError, ToolNotFoundError,
                                    ToolRegistrationError)
from agent_framework.executor import ToolExecutor
from agent_framework.hooks import ArgumentPolicyHook, LoggingHook, ToolHook
from agent_framework.hygiene import SAFETY_PREAMBLE, OutputSanitizer
from agent_framework.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from agent_framework.memory import CharEstimateCounter, ConversationMemory, TokenCounter
from agent_framework.messages import (Message, ModelResponse, Role, StopReason, TextBlock,
                                      ToolResultBlock, ToolUseBlock, Usage)
from agent_framework.model import Model, ScriptedModel, call, say
from agent_framework.permissions import (Approver, DenyAllApprover, Permission,
                                         PermissionPolicy, ScriptedApprover)
from agent_framework.tools import FunctionTool, Tool, ToolRegistry
from agent_framework.wiring import build_agent

__all__ = [
    "Agent", "AgentResult", "RunStatus", "Clock", "FakeClock", "SystemClock", "AgentConfig",
    "AgentError", "ConfigError", "ConversationError", "ModelError", "PermissionDeniedError",
    "SchemaError", "ToolError", "ToolExecutionError", "ToolInputError", "ToolNotFoundError",
    "ToolRegistrationError", "ToolExecutor", "ArgumentPolicyHook", "LoggingHook", "ToolHook",
    "SAFETY_PREAMBLE", "OutputSanitizer", "IdempotencyStore", "InMemoryIdempotencyStore",
    "CharEstimateCounter", "ConversationMemory", "TokenCounter", "Message", "ModelResponse",
    "Role", "StopReason", "TextBlock", "ToolResultBlock", "ToolUseBlock", "Usage", "Model",
    "ScriptedModel", "call", "say", "Approver", "DenyAllApprover", "Permission",
    "PermissionPolicy", "ScriptedApprover", "FunctionTool", "Tool", "ToolRegistry",
    "build_agent",
]


# A library never configures logging; the application does. The NullHandler
# stops Python printing our warnings when the application has set nothing up.
logging.getLogger(__name__).addHandler(logging.NullHandler())
