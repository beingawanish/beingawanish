"""Swarm: peer agents coordinate through a shared blackboard, with no controller.

Each tick, every agent looks at the board and claims at most one open task that
matches its skills (claims are atomic), works it, writes the result, and may post
follow-up tasks. Behaviour emerges from these local rules. Code owns the only global
controls a swarm has: a tick budget, a cap on total tasks, and de-duplication of
identical tasks.

Ticks run agents in a fixed order, so runs are deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json


@dataclass
class Task:
    id: str
    kind: str
    payload: str
    status: str = "open"  # open | claimed | done
    claimed_by: Optional[str] = None
    result: str = ""
    posted_by: str = "user"


@dataclass
class SwarmAgent:
    name: str
    skills: frozenset[str]
    llm: LLM


@dataclass
class Blackboard:
    tasks: list[Task] = field(default_factory=list)
    max_tasks: int = 30
    rejected: int = 0

    def post(self, kind: str, payload: str, by: str) -> Optional[Task]:
        if any(t.kind == kind and t.payload == payload for t in self.tasks):
            return None  # de-duplicate: identical work is never posted twice
        if len(self.tasks) >= self.max_tasks:
            self.rejected += 1
            return None
        t = Task(f"T{len(self.tasks) + 1}", kind, payload, posted_by=by)
        self.tasks.append(t)
        return t

    def claim(self, agent: SwarmAgent) -> Optional[Task]:
        for t in self.tasks:
            if t.status == "open" and t.kind in agent.skills:
                t.status, t.claimed_by = "claimed", agent.name
                return t
        return None

    def open_count(self) -> int:
        return sum(t.status != "done" for t in self.tasks)


@dataclass
class SwarmRun:
    ticks: int
    calls: int
    done: int
    unfinished: int
    stop_reason: str


def run_swarm(board: Blackboard, agents: list[SwarmAgent], max_ticks: int = 10,
              trace: Optional[Trace] = None) -> SwarmRun:
    calls = 0
    for tick in range(1, max_ticks + 1):
        worked = False
        for agent in agents:
            task = board.claim(agent)
            if not task:
                continue
            worked = True
            calls += 1
            msg = extract_json(agent.llm.complete(f"WORK {task.kind}: {task.payload}\n"
                                                  'Reply {"result": "...", "post": [{"kind", "payload"}]}'))
            task.result, task.status = str(msg["result"]), "done"
            posted = [board.post(p["kind"], p["payload"], agent.name) for p in msg.get("post", [])]
            new = [p.id for p in posted if p]
            if trace:
                trace.step(f"t{tick} {agent.name}", f"{task.id} {task.kind}: {task.result}" + (f" → posted {new}" if new else ""))
        if board.open_count() == 0:
            return SwarmRun(tick, calls, len(board.tasks), 0, "board empty")
        if not worked:
            return SwarmRun(tick, calls, sum(t.status == "done" for t in board.tasks), board.open_count(),
                            "stalled: unfinished tasks, but no agent could make progress")
    return SwarmRun(max_ticks, calls, sum(t.status == "done" for t in board.tasks), board.open_count(),
                    f"tick budget {max_ticks} spent")
