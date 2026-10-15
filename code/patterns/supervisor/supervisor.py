"""Supervisor: one coordinating agent repeatedly picks which specialist acts next.

Hub-and-spoke and multi-turn: after every worker turn the supervisor sees the result
and decides again — another worker, the same worker with a new instruction, or
FINISH. Code validates every decision and owns the turn budget and loop detection.

Reused by hierarchical teams (#13) and the coding-team capstone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agentkit import LLM, Trace, extract_json

# A worker is any callable taking (instruction, shared_state) and returning text.
Worker = Callable[[str, dict], str]


@dataclass
class SupervisorRun:
    ok: bool
    final: str
    turns: list[tuple[str, str, str]] = field(default_factory=list)  # (worker, instruction, output)
    stop_reason: str = ""


class Supervisor:
    def __init__(self, llm: LLM, workers: dict[str, Worker], descriptions: dict[str, str],
                 max_turns: int = 8, name: str = "supervisor") -> None:
        self.llm, self.workers, self.descriptions = llm, workers, descriptions
        self.max_turns, self.name = max_turns, name

    def _decide(self, task: str, run: SupervisorRun) -> dict:
        roster = "\n".join(f"- {w}: {d}" for w, d in self.descriptions.items())
        history = "\n".join(f"[{w}] ({i}) -> {o}" for w, i, o in run.turns) or "(nothing yet)"
        raw = self.llm.complete(
            f"SUPERVISE task: {task}\nWorkers:\n{roster}\nHistory:\n{history}\n"
            'Reply {"next": "<worker>|FINISH", "instruction": "...", "final": "<answer if FINISH>"}',
            system=f"You are the {self.name}. Delegate; do not do the work yourself.")
        return extract_json(raw)

    def run(self, task: str, state: Optional[dict] = None, trace: Optional[Trace] = None) -> SupervisorRun:
        state = state if state is not None else {}
        run = SupervisorRun(False, "")
        for _ in range(self.max_turns):
            try:
                d = self._decide(task, run)
                nxt, instruction = str(d["next"]), str(d.get("instruction", ""))
            except (ValueError, KeyError) as exc:
                run.stop_reason = f"invalid decision: {exc}"
                return run
            if nxt == "FINISH":
                run.ok, run.final, run.stop_reason = True, str(d.get("final", "")), "finished"
                if trace:
                    trace.step(f"{self.name}", f"FINISH: {run.final}")
                return run
            if nxt not in self.workers:
                run.stop_reason = f"unknown worker '{nxt}'"
                if trace:
                    trace.step(f"{self.name}", f"STOP — {run.stop_reason}")
                return run
            if any(w == nxt and i == instruction for w, i, _ in run.turns):
                run.stop_reason = f"loop: {nxt} already did '{instruction}'"
                if trace:
                    trace.step(f"{self.name}", f"STOP — {run.stop_reason}")
                return run
            if trace:
                trace.step(f"{self.name} → {nxt}", instruction)
            out = self.workers[nxt](instruction, state)
            run.turns.append((nxt, instruction, out))
            if trace:
                trace.step(f"{nxt}", out)
        run.stop_reason = f"turn budget {self.max_turns} spent"
        return run
