"""Prompt chaining: a fixed sequence of LLM calls with code gates between steps."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agentkit import LLM, Trace

# A gate inspects a step's output and returns None (pass) or a reason string (stop).
Gate = Callable[[str], Optional[str]]


@dataclass
class Step:
    name: str
    template: str  # must contain "{input}"; receives the previous step's output
    system: str = ""
    gate: Optional[Gate] = None


@dataclass
class ChainResult:
    ok: bool
    output: str
    outputs: dict[str, str] = field(default_factory=dict)
    stopped_at: Optional[str] = None
    reason: Optional[str] = None


def run_chain(llm: LLM, steps: list[Step], text: str, trace: Optional[Trace] = None) -> ChainResult:
    outputs: dict[str, str] = {}
    current = text
    for step in steps:
        current = llm.complete(step.template.format(input=current), system=step.system).strip()
        outputs[step.name] = current
        if trace:
            trace.step(step.name, current.replace("\n", " | "))
        if step.gate:
            reason = step.gate(current)
            if reason:
                if trace:
                    trace.step(f"gate:{step.name}", f"STOP — {reason}")
                return ChainResult(False, current, outputs, step.name, reason)
            if trace:
                trace.step(f"gate:{step.name}", "pass")
    return ChainResult(True, current, outputs)
