"""ReAct: interleave Thought -> Action -> Observation in one growing trace.

The model writes free-text steps in a fixed format; code parses each Action, runs
the tool, and appends the Observation. The trace *is* the prompt for the next step,
so every decision is grounded in what was actually observed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, ToolError, ToolRegistry, Trace

FORMAT = (
    "Answer the question by alternating lines:\n"
    "Thought: <your reasoning>\nAction: <tool>[<input>]\n"
    "You will then see 'Observation: <result>'. When you know the answer write:\n"
    "Thought: <reasoning>\nFinal Answer: <answer>"
)
ACTION = re.compile(r"^Action:\s*(\w+)\[(.*)\]\s*$", re.MULTILINE)
FINAL = re.compile(r"^Final Answer:\s*(.+)$", re.MULTILINE | re.DOTALL)


@dataclass
class ReActResult:
    answer: Optional[str]
    steps: int
    stop_reason: str  # "answered" | "max_steps" | "repeated_action"
    scratchpad: list[str] = field(default_factory=list)


def react(llm: LLM, tools: ToolRegistry, question: str, max_steps: int = 6,
          trace: Optional[Trace] = None) -> ReActResult:
    """Each tool takes a single string argument named ``q``."""
    pad: list[str] = []
    seen: set[tuple[str, str]] = set()
    for step in range(1, max_steps + 1):
        prompt = f"{FORMAT}\nTools:\n{tools.specs()}\n\nQuestion: {question}\n" + "\n".join(pad)
        out = llm.complete(prompt, system="You are a careful ReAct agent.").strip()
        thought = next((ln[8:].strip() for ln in out.splitlines() if ln.startswith("Thought:")), "")
        if trace and thought:
            trace.step(f"thought {step}", thought)
        final = FINAL.search(out)
        if final:
            pad.append(out)
            if trace:
                trace.step("final", final.group(1).strip())
            return ReActResult(final.group(1).strip(), step, "answered", pad)
        action = ACTION.search(out)
        if not action:
            obs = "Invalid format: write exactly one 'Action: tool[input]' or a 'Final Answer:'."
        else:
            name, arg = action.group(1), action.group(2).strip()
            if (name, arg) in seen:
                if trace:
                    trace.step("stop", f"repeated action {name}[{arg}] — not making progress")
                return ReActResult(None, step, "repeated_action", pad)
            seen.add((name, arg))
            if trace:
                trace.step(f"action {step}", f"{name}[{arg}]")
            try:
                obs = str(tools.call(name, {"q": arg}))
            except ToolError as exc:
                obs = f"Error: {exc}"
        pad.append(f"{out}\nObservation: {obs}")
        if trace:
            trace.step(f"observe {step}", obs)
    return ReActResult(None, max_steps, "max_steps", pad)
