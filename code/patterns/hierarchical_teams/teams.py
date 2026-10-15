"""Hierarchical teams: supervisors of supervisors.

A team is a Supervisor over its own workers, with its own private state. Wrapped by
``team_as_worker``, a whole team looks like a single worker to the level above: it
receives one instruction and returns one summary. Detail stays inside the team —
that context scoping is the point of the pattern.

Reused by the coding-team capstone.
"""

from __future__ import annotations

from typing import Callable, Optional

from agentkit import Trace
from patterns.supervisor.supervisor import Supervisor, SupervisorRun, Worker


def team_as_worker(team: Supervisor, summarise: Optional[Callable[[SupervisorRun], str]] = None,
                   trace: Optional[Trace] = None) -> Worker:
    """Expose a team as one worker. The parent sees only the team's summary."""

    def run(instruction: str, parent_state: dict) -> str:
        private: dict = {}  # the team's working state never leaks upward
        result = team.run(instruction, private, trace=trace)
        if not result.ok:
            return f"[{team.name} failed: {result.stop_reason}]"
        summary = summarise(result) if summarise else result.final
        parent_state.setdefault("team_outputs", {})[team.name] = summary
        return summary

    return run
