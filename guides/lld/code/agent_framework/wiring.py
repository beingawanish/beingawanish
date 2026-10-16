"""Composition root: the one place that knows every concrete class.

Every argument has a safe default and every default can be swapped. Pass the
same `store` to a new agent and a retried run_id will not repeat side effects.
"""
import uuid
from collections.abc import Callable, Sequence

from agent_framework.agent import Agent
from agent_framework.clock import Clock, SystemClock
from agent_framework.config import AgentConfig
from agent_framework.executor import ToolExecutor
from agent_framework.hooks import LoggingHook, ToolHook
from agent_framework.hygiene import OutputSanitizer
from agent_framework.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from agent_framework.memory import CharEstimateCounter, ConversationMemory
from agent_framework.model import Model
from agent_framework.permissions import Approver, DenyAllApprover, PermissionPolicy
from agent_framework.tools import ToolRegistry


def build_agent(model: Model, registry: ToolRegistry, *, system: str = "",
                config: AgentConfig | None = None, policy: PermissionPolicy | None = None,
                approver: Approver | None = None, hooks: Sequence[ToolHook] | None = None,
                clock: Clock | None = None, store: IdempotencyStore | None = None,
                new_run_id: Callable[[], str] | None = None) -> Agent:
    config = config or AgentConfig()
    clock = clock or SystemClock()
    executor = ToolExecutor(
        registry=registry,
        policy=policy or PermissionPolicy(),
        approver=approver or DenyAllApprover(),
        hooks=[LoggingHook(clock)] if hooks is None else hooks,
        store=store or InMemoryIdempotencyStore(clock, config.idempotency_ttl_seconds),
        sanitizer=OutputSanitizer(config),
        config=config,
    )
    memory = ConversationMemory(config, CharEstimateCounter(config))
    return Agent(model, registry, executor, memory, config, system,
                 new_run_id or (lambda: uuid.uuid4().hex))
