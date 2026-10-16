"""The agent loop.

    call model -> run the tool_use blocks -> append all results in one user
    message -> repeat, until the model ends its turn or a budget runs out.

Budgets end a run with a status, not an exception. Running out of steps is
an expected outcome, and the caller still wants the partial transcript.
Model failures (ModelError) do propagate: the model cannot fix those.
"""
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from agent_framework.config import AgentConfig
from agent_framework.errors import ConversationError, ModelError
from agent_framework.executor import ToolExecutor
from agent_framework.hygiene import SAFETY_PREAMBLE
from agent_framework.memory import ConversationMemory
from agent_framework.messages import Message, Role, StopReason, ToolResultBlock, Usage
from agent_framework.model import Model
from agent_framework.tools import ToolRegistry

log = logging.getLogger(__name__)


class RunStatus(Enum):
    COMPLETED = "completed"
    STEP_BUDGET_EXHAUSTED = "step_budget_exhausted"
    TOKEN_BUDGET_EXHAUSTED = "token_budget_exhausted"
    TRUNCATED = "truncated"   # stop_reason max_tokens: tool inputs may be cut off
    REFUSED = "refused"


@dataclass(frozen=True)
class AgentResult:
    status: RunStatus
    final_text: str
    steps: int
    usage: Usage
    run_id: str


class Agent:
    """One Agent = one conversation. run() holds a lock, so two threads cannot
    interleave turns in the same memory."""

    def __init__(self, model: Model, registry: ToolRegistry, executor: ToolExecutor,
                 memory: ConversationMemory, config: AgentConfig, system: str = "",
                 new_run_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._model = model
        self._registry = registry
        self._executor = executor
        self._memory = memory
        self._config = config
        self._system = f"{SAFETY_PREAMBLE}\n\n{system}".strip()
        self._new_run_id = new_run_id
        self._run_lock = threading.Lock()  # serialises whole runs on this conversation

    def run(self, task: str, run_id: str | None = None) -> AgentResult:
        """Pass the run_id of a crashed run to retry it without repeating side effects."""
        if not task.strip():
            raise ConversationError("task must not be blank")
        with self._run_lock:
            return self._loop(task, run_id or self._new_run_id())

    def _loop(self, task: str, run_id: str) -> AgentResult:
        self._memory.append(Message.user_text(task))
        usage, text = Usage(), ""
        for step in range(1, self._config.max_steps + 1):
            if usage.total >= self._config.max_total_tokens:
                return self._finish(RunStatus.TOKEN_BUDGET_EXHAUSTED, text, step - 1, usage, run_id)
            response = self._model.complete(self._system, self._memory.window(),
                                            self._registry.definitions())
            usage = usage + response.usage
            reply = response.as_message()
            self._memory.append(reply)
            text = reply.text() or text
            log.info("step %d stop_reason=%s tokens=%d", step, response.stop_reason.value,
                     usage.total)
            match response.stop_reason:
                case StopReason.END_TURN:
                    return self._finish(RunStatus.COMPLETED, text, step, usage, run_id)
                case StopReason.MAX_TOKENS:
                    # Never run a tool_use that may be cut off. Close it with an
                    # error result so the transcript stays valid for the next run.
                    unrun = [ToolResultBlock(c.id, "not run: the request was truncated", True)
                             for c in reply.tool_uses()]
                    if unrun:
                        self._memory.append(Message(Role.USER, tuple(unrun)))
                    return self._finish(RunStatus.TRUNCATED, text, step, usage, run_id)
                case StopReason.REFUSAL:
                    return self._finish(RunStatus.REFUSED, text, step, usage, run_id)
                case StopReason.TOOL_USE:
                    calls = reply.tool_uses()
                    if not calls:
                        raise ModelError("stop_reason tool_use with no tool_use blocks")
                    results = self._executor.execute(calls, run_id)
                    # Every result in ONE user message, in request order.
                    self._memory.append(Message(Role.USER, tuple(results)))
        return self._finish(RunStatus.STEP_BUDGET_EXHAUSTED, text,
                            self._config.max_steps, usage, run_id)

    def _finish(self, status: RunStatus, text: str, steps: int, usage: Usage,
                run_id: str) -> AgentResult:
        log.info("run %s finished: %s after %d steps, %d tokens",
                 run_id, status.value, steps, usage.total)
        return AgentResult(status, text, steps, usage, run_id)
