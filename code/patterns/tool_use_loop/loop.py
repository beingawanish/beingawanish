"""Tool-use loop: the canonical agent runtime.

model emits a structured call -> host validates and executes -> result is appended
-> repeat until the model emits a final answer or a limit trips.

The host, not the model, owns: argument validation, error-to-observation conversion,
confirmation of side-effecting tools, and every stop condition. Reused by the
coding-team capstone (with a context manager plugged into ``render``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from agentkit import LLM, ToolError, ToolRegistry, Trace, extract_json

PROTOCOL = ('Reply with ONE JSON object: {"tool": "<name>", "args": {...}} to call a tool, '
            'or {"final": "<answer>"} when done.')


@dataclass
class LoopResult:
    final: Optional[str]
    steps: int
    stop_reason: str  # "final" | "max_steps" | "too_many_errors"
    transcript: list[dict] = field(default_factory=list)


def default_render(system: str, tool_specs: str, transcript: list[dict]) -> str:
    lines = [f"{system}\n{PROTOCOL}\nTools:\n{tool_specs}\n"]
    for m in transcript:
        lines.append(f"{m['role'].upper()}: {m['content']}")
    return "\n".join(lines)


class ToolLoop:
    def __init__(
        self,
        llm: LLM,
        tools: ToolRegistry,
        system: str = "You are a helpful agent that uses tools.",
        max_steps: int = 8,
        max_errors: int = 3,
        require_confirm: frozenset[str] = frozenset(),
        confirm: Optional[Callable[[str, dict], bool]] = None,
        render: Optional[Callable[[str, str, list[dict]], str]] = None,
    ) -> None:
        self.llm, self.tools, self.system = llm, tools, system
        self.max_steps, self.max_errors = max_steps, max_errors
        self.require_confirm, self.confirm = require_confirm, confirm or (lambda name, args: False)
        self.render = render or default_render

    def run(self, task: str, transcript: Optional[list[dict]] = None, trace: Optional[Trace] = None) -> LoopResult:
        t = list(transcript or []) + [{"role": "user", "content": task}]
        errors = 0
        for step in range(1, self.max_steps + 1):
            raw = self.llm.complete(self.render(self.system, self.tools.specs(), t))
            t.append({"role": "assistant", "content": raw.strip()})
            try:
                msg = extract_json(raw)
                if not isinstance(msg, dict):
                    raise ValueError("expected a JSON object")
            except ValueError as exc:
                obs, ok = f"ERROR: {exc}. {PROTOCOL}", False
            else:
                if "final" in msg:
                    if trace:
                        trace.step("final", str(msg["final"]))
                    return LoopResult(str(msg["final"]), step, "final", t)
                name, args = str(msg.get("tool")), msg.get("args", {})
                if trace:
                    trace.step(f"call {step}", f"{name}({json.dumps(args, ensure_ascii=False)})")
                if name in self.require_confirm and not self.confirm(name, args):
                    obs, ok = f"ERROR: {name} was not approved by the user. Ask or choose another action.", False
                else:
                    try:
                        obs, ok = json.dumps(self.tools.call(name, args if isinstance(args, dict) else {}),
                                             ensure_ascii=False), True
                    except ToolError as exc:
                        obs, ok = f"ERROR: {exc}", False
            t.append({"role": "tool", "content": obs})
            if trace:
                trace.step(f"result {step}", obs)
            errors = 0 if ok else errors + 1
            if errors >= self.max_errors:
                if trace:
                    trace.step("stop", f"{errors} consecutive errors")
                return LoopResult(None, step, "too_many_errors", t)
        if trace:
            trace.step("stop", f"step limit {self.max_steps} reached")
        return LoopResult(None, self.max_steps, "max_steps", t)
