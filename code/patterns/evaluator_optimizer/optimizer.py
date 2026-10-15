"""Evaluator-optimizer: a generator and a separate rubric-driven evaluator loop until pass.

Stops on: pass, round budget exhausted, or *stall* (the evaluator repeats the same
feedback, meaning the generator is not converging — more rounds would just burn money).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json

EVAL_SYSTEM = "You are a strict evaluator. You did not write the draft. Reply with JSON only."


@dataclass
class Evaluation:
    passed: bool
    feedback: list[str]


@dataclass
class OptimizeResult:
    output: str
    passed: bool
    rounds: int
    stop_reason: str  # "passed" | "budget" | "stalled"
    history: list[tuple[str, Evaluation]] = field(default_factory=list)


def evaluate(evaluator: LLM, task: str, rubric: list[str], draft: str) -> Evaluation:
    criteria = "\n".join(f"{i}. {c}" for i, c in enumerate(rubric, 1))
    prompt = (
        f"EVALUATE the draft for the task against every criterion.\nTask: {task}\n"
        f"Criteria:\n{criteria}\n\nDraft:\n{draft}\n\n"
        'Reply {"pass": bool, "feedback": ["<one actionable fix per failed criterion>"]}'
    )
    try:
        data = extract_json(evaluator.complete(prompt, system=EVAL_SYSTEM))
        return Evaluation(bool(data["pass"]), [str(f) for f in data.get("feedback", [])])
    except (ValueError, KeyError) as exc:
        return Evaluation(False, [f"(evaluator output unusable: {exc})"])


def optimize(
    generator: LLM,
    evaluator: LLM,
    task: str,
    rubric: list[str],
    max_rounds: int = 3,
    trace: Optional[Trace] = None,
) -> OptimizeResult:
    history: list[tuple[str, Evaluation]] = []
    prompt = f"WRITE: {task}"
    for rnd in range(1, max_rounds + 1):
        draft = generator.complete(prompt, system="You are a careful writer.").strip()
        ev = evaluate(evaluator, task, rubric, draft)
        history.append((draft, ev))
        if trace:
            trace.step(f"round {rnd} draft", draft)
            trace.step(f"round {rnd} eval", "PASS" if ev.passed else "FAIL: " + "; ".join(ev.feedback))
        if ev.passed:
            return OptimizeResult(draft, True, rnd, "passed", history)
        if len(history) >= 2 and history[-2][1].feedback == ev.feedback:
            return OptimizeResult(draft, False, rnd, "stalled", history)
        prompt = (
            f"WRITE: {task}\n\nREVISE your previous draft.\nPrevious draft:\n{draft}\n"
            "Fix ALL of this feedback:\n" + "\n".join(f"- {f}" for f in ev.feedback)
        )
    return OptimizeResult(history[-1][0], False, max_rounds, "budget", history)
