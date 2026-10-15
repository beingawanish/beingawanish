"""Plan-and-execute with re-planning.

A planner model writes the whole plan up front as JSON. An executor runs steps one
at a time — usually without a large model (here: a plain callable). When a step
fails, or its result invalidates the rest of the plan, the planner is called again
with what has happened so far and writes a new *remaining* plan.

Reused by the deep-research capstone, where each step is an agentic-RAG lookup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agentkit import LLM, Trace, extract_json


@dataclass
class Step:
    id: str
    action: str
    args: dict[str, Any]
    purpose: str = ""


@dataclass
class StepResult:
    ok: bool
    output: Any
    note: str = ""


@dataclass
class PlanRun:
    ok: bool
    results: dict[str, StepResult] = field(default_factory=dict)
    plans: list[list[Step]] = field(default_factory=list)  # every plan version
    replans: int = 0
    stop_reason: str = ""


Executor = Callable[[Step, dict[str, StepResult]], StepResult]
# Optional cheap fix before paying for a re-plan: given the failed step, its result,
# the remaining plan and all results, return a repaired remaining plan or None.
Repair = Callable[[Step, StepResult, list[Step], dict[str, StepResult]], Optional[list[Step]]]


def _parse_plan(raw: str, allowed: set[str], max_steps: int) -> list[Step]:
    data = extract_json(raw)
    if not isinstance(data, list) or not data:
        raise ValueError("plan must be a non-empty JSON list")
    steps = [Step(str(d["id"]), str(d["action"]), dict(d.get("args", {})), str(d.get("purpose", ""))) for d in data]
    bad = [s.action for s in steps if s.action not in allowed]
    if bad:
        raise ValueError(f"unknown action(s) {bad}")
    if len(steps) > max_steps:
        raise ValueError(f"plan has {len(steps)} steps (max {max_steps})")
    return steps


def _done(results: dict[str, StepResult]) -> str:
    return json.dumps({k: {"ok": v.ok, "output": v.output, "note": v.note} for k, v in results.items()})


def plan_and_execute(
    planner: LLM,
    goal: str,
    actions: dict[str, str],  # action name -> description (the planner's menu)
    execute: Executor,
    max_replans: int = 2,
    max_steps: int = 8,
    trace: Optional[Trace] = None,
    repair: Optional[Repair] = None,
) -> PlanRun:
    menu = "\n".join(f"- {a}: {d}" for a, d in actions.items())
    run = PlanRun(ok=False)
    prompt = (f"PLAN for goal: {goal}\nActions:\n{menu}\n"
              'Reply with a JSON list of {"id", "action", "args", "purpose"}.')
    try:
        plan = _parse_plan(planner.complete(prompt, system="You are the planner."), set(actions), max_steps)
    except (ValueError, KeyError) as exc:
        run.stop_reason = f"invalid plan: {exc}"
        return run
    run.plans.append(plan)
    if trace:
        trace.step("plan v1", " → ".join(f"{s.id}:{s.action}" for s in plan))

    while plan:
        step = plan.pop(0)
        result = execute(step, run.results)
        run.results[step.id] = result
        if trace:
            trace.step(f"exec {step.id}", ("ok  " if result.ok else "FAIL ") + str(result.output) +
                       (f" ({result.note})" if result.note else ""))
        if result.ok:
            continue
        fixed = repair(step, result, plan, run.results) if repair else None
        if fixed is not None:
            plan = fixed
            if trace:
                trace.step("local repair", " → ".join(f"{s.id}:{s.action}" for s in plan))
            continue
        if run.replans >= max_replans:
            run.stop_reason = f"step {step.id} failed and re-plan budget is spent"
            return run
        run.replans += 1
        replan_prompt = (f"REPLAN for goal: {goal}\nActions:\n{menu}\nResults so far: {_done(run.results)}\n"
                         f"Step {step.id} failed. Write the REMAINING steps only as a JSON list.")
        try:
            plan = _parse_plan(planner.complete(replan_prompt, system="You are the planner."), set(actions), max_steps)
        except (ValueError, KeyError) as exc:
            run.stop_reason = f"invalid re-plan: {exc}"
            return run
        run.plans.append(plan)
        if trace:
            trace.step(f"plan v{len(run.plans)}", " → ".join(f"{s.id}:{s.action}" for s in plan))
    run.ok, run.stop_reason = True, "completed"
    return run
