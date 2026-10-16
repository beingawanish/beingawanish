"""Reflection / self-critique: the same model reviews its own output and revises it.

No separate judge, no rubric file, no tools: just a critique prompt aimed at the
model's own draft. Cheap, and limited by the model's own blind spots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace

NO_ISSUES = "NO ISSUES"


@dataclass
class ReflectionResult:
    output: str
    rounds: int  # number of revisions made
    first_draft: str = ""
    critiques: list[str] = field(default_factory=list)


def reflect(llm: LLM, task: str, max_rounds: int = 2, system: str = "",
            trace: Optional[Trace] = None) -> ReflectionResult:
    draft = first = llm.complete(f"TASK: {task}", system=system).strip()
    if trace:
        trace.step("draft", draft.splitlines()[0] + (" …" if "\n" in draft else ""))
    critiques: list[str] = []
    for rnd in range(1, max_rounds + 1):
        critique = llm.complete(
            f"TASK: {task}\nYOUR ANSWER:\n{draft}\n\nCRITIQUE your answer: list concrete errors, "
            f"edge cases you missed, or unsupported claims. If there are none, reply exactly {NO_ISSUES}.",
            system=system,
        ).strip()
        critiques.append(critique)
        if trace:
            trace.step(f"critique {rnd}", critique)
        if critique.upper().startswith(NO_ISSUES):
            return ReflectionResult(draft, rnd - 1, first, critiques)
        draft = llm.complete(
            f"TASK: {task}\nYOUR ANSWER:\n{draft}\nYOUR CRITIQUE:\n{critique}\n\nREVISE the answer to fix every point.",
            system=system,
        ).strip()
        if trace:
            trace.step(f"revision {rnd}", draft.splitlines()[0] + (" …" if "\n" in draft else ""))
    return ReflectionResult(draft, max_rounds, first, critiques)
