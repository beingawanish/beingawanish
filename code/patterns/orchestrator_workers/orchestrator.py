"""Orchestrator-workers: an LLM decomposes the task at runtime, workers run the pieces,
a synthesis call merges them. Single pass — no re-planning (that is plan-and-execute).

Workers run concurrently via the parallelization module's ``fan_out`` (reused, not
re-implemented).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json
from patterns.parallelization.fanout import fan_out


@dataclass
class Subtask:
    id: str
    instruction: str
    source: str  # key into the context store the worker may read


@dataclass
class OrchestrationResult:
    ok: bool
    final: str
    subtasks: list[Subtask] = field(default_factory=list)
    worker_outputs: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


def plan(llm: LLM, task: str, sources: list[str], max_subtasks: int) -> list[Subtask]:
    prompt = (
        f"TASK: {task}\nAvailable sources: {', '.join(sources)}\n"
        f"Decompose into at most {max_subtasks} independent subtasks. Reply with a JSON list of "
        '{"id", "instruction", "source"}.'
    )
    data = extract_json(llm.complete(prompt, system="You are the orchestrator."))
    if not isinstance(data, list) or not data:
        raise ValueError("plan must be a non-empty JSON list")
    subtasks = [Subtask(str(d["id"]), str(d["instruction"]), str(d["source"])) for d in data]
    if len(subtasks) > max_subtasks:
        raise ValueError(f"plan has {len(subtasks)} subtasks (max {max_subtasks})")
    unknown = [s.source for s in subtasks if s.source not in sources]
    if unknown:
        raise ValueError(f"plan references unknown sources {unknown}")
    return subtasks


def orchestrate(
    orchestrator: LLM,
    worker: LLM,
    task: str,
    store: dict[str, str],
    max_subtasks: int = 5,
    trace: Optional[Trace] = None,
) -> OrchestrationResult:
    try:
        subtasks = plan(orchestrator, task, list(store), max_subtasks)
    except (ValueError, KeyError) as exc:
        if trace:
            trace.step("plan", f"REJECTED — {exc}")
        return OrchestrationResult(False, "", error=str(exc))
    if trace:
        trace.step("plan", f"{len(subtasks)} subtask(s): " + ", ".join(s.id for s in subtasks))

    jobs = {
        s.id: (lambda s=s: worker.complete(f"{s.instruction}\n\nSOURCE {s.source}:\n{store[s.source]}",
                                           system="You are a worker. Do only your subtask."))
        for s in subtasks
    }
    outputs: dict[str, str] = {}
    for b in fan_out(jobs):
        outputs[b.name] = b.value if b.ok else f"[worker failed: {b.error}]"
        if trace:
            trace.step(f"worker:{b.name}", outputs[b.name])

    pieces = "\n".join(f"- ({k}) {v}" for k, v in outputs.items())
    final = orchestrator.complete(f"SYNTHESIZE for task: {task}\n{pieces}", system="You are the orchestrator.")
    if trace:
        trace.step("synthesize", final.replace("\n", " | "))
    return OrchestrationResult(True, final, subtasks, outputs)
