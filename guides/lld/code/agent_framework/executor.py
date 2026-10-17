"""The tool executor: one batch of tool_use blocks in, one tool_result per block out.

Per call, in order: look up -> validate -> [replay a stored result?] ->
permission -> before-hooks -> run -> sanitise -> after-hooks.

The replay check comes before permission on purpose. A duplicate of an
approved side effect runs nothing, so there is nothing to ask a human about.

Any ToolError along the way becomes an is_error result. An exception from
the tool's own code is wrapped as ToolExecutionError first. Nothing a tool
does can crash the loop.

Batching: parallel-safe calls go to a thread pool. The rest run one by one,
in the order the model listed them. Results come back in request order.
"""
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from agent_framework.config import AgentConfig
from agent_framework.errors import PermissionDeniedError, ToolError, ToolExecutionError
from agent_framework.hooks import ToolHook
from agent_framework.hygiene import OutputSanitizer
from agent_framework.idempotency import IdempotencyStore, idempotency_key
from agent_framework.messages import ToolResultBlock, ToolUseBlock
from agent_framework.permissions import Approver, PermissionPolicy
from agent_framework.schema import validate
from agent_framework.tools import Tool, ToolRegistry

log = logging.getLogger(__name__)

REPLAY_NOTE = "[duplicate call: the action was not repeated; this is the original result]\n"


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: PermissionPolicy, approver: Approver,
                 hooks: Sequence[ToolHook], store: IdempotencyStore,
                 sanitizer: OutputSanitizer, config: AgentConfig) -> None:
        self._registry = registry
        self._policy = policy
        self._approver = approver
        self._hooks = list(hooks)
        self._store = store
        self._sanitizer = sanitizer
        self._max_workers = config.max_parallel_tools

    def execute(self, calls: Sequence[ToolUseBlock], run_id: str) -> list[ToolResultBlock]:
        results: dict[str, ToolResultBlock] = {}
        parallel = [c for c in calls if self._is_parallel_safe(c)]
        serial = [c for c in calls if not self._is_parallel_safe(c)]
        with ThreadPoolExecutor(max_workers=self._max_workers,
                                thread_name_prefix="tool") as pool:
            futures: dict[str, Future[ToolResultBlock]] = {
                c.id: pool.submit(self._execute_one, c, run_id) for c in parallel}
            for c in serial:  # on this thread, in model order, while the pool works
                results[c.id] = self._execute_one(c, run_id)
            for call_id, future in futures.items():
                results[call_id] = future.result()
        return [results[c.id] for c in calls]

    def _is_parallel_safe(self, call: ToolUseBlock) -> bool:
        try:
            return self._registry.get(call.name).parallel_safe
        except ToolError:
            return True  # unknown tool: it will only produce an error result

    def _execute_one(self, call: ToolUseBlock, run_id: str) -> ToolResultBlock:
        try:
            tool = self._registry.get(call.name)
            validate(call.input, tool.input_schema)

            def gated() -> str:  # runs only if there is no stored result to replay
                self._policy.enforce(call, tool, self._approver)
                for hook in self._hooks:
                    reason = hook.before(call)
                    if reason:
                        raise PermissionDeniedError(f"blocked by policy: {reason}")
                return self._invoke(tool, call)

            output = self._once(tool, call, run_id, gated)
            result = ToolResultBlock(call.id, self._sanitizer.clean(tool.name, output))
        except ToolError as exc:
            log.warning("tool %s (%s) failed: %s: %s", call.name, call.id,
                        type(exc).__name__, exc)
            text = f"{type(exc).__name__}: {exc}"
            result = ToolResultBlock(call.id, self._sanitizer.clean(call.name, text, True), True)
        for hook in reversed(self._hooks):
            result = hook.after(call, result)
        return result

    @staticmethod
    def _invoke(tool: Tool, call: ToolUseBlock) -> str:
        try:
            return tool.run(call.input)
        except ToolError:
            raise
        except Exception as exc:  # tool code is foreign; any failure becomes a result
            raise ToolExecutionError(str(exc) or type(exc).__name__) from exc

    def _once(self, tool: Tool, call: ToolUseBlock, run_id: str,
              gated: Callable[[], str]) -> str:
        if not tool.side_effects:
            return gated()
        output, replayed = self._store.run_once(
            idempotency_key(run_id, tool.name, call.input), gated)
        if replayed:
            log.info("idempotent replay of %s (%s)", tool.name, call.id)
            return REPLAY_NOTE + output
        return output
