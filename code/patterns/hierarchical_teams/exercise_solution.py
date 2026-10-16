"""Exercise solution — Hierarchical teams.

Task: one worker deep inside a team raises an exception. Today the exception
propagates up and kills the entire hierarchy. Contain failures at the worker
boundary so the team lead sees an error result, can finish (or not) on its own
terms, and the level above receives a summary instead of a crash.

Run:  python3 code/patterns/hierarchical_teams/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.hierarchical_teams.main import lead, writer  # noqa: E402
from patterns.hierarchical_teams.teams import team_as_worker  # noqa: E402
from patterns.supervisor.supervisor import Supervisor  # noqa: E402


def contained(worker):
    """Turn a worker exception into an error *result* the supervisor can reason about."""
    def run(instruction, state):
        try:
            return worker(instruction, state)
        except Exception as exc:
            return f"[error: {type(exc).__name__}: {exc}]"
    return run


def broken_editor(i, s):
    raise TimeoutError("style-guide service unavailable")


def content_lead_policy(prompt, system):
    history = prompt.split("History:\n", 1)[1]
    if "[editor]" in history and "[error" in history:
        return json.dumps({"next": "FINISH", "final": "Unedited headline (editor unavailable): "
                                                       "'Scheduled exports are here — set it once.'"})
    return lead([("writer", "Draft"), ("editor", "Tighten")], "")(prompt, system)


def main() -> None:
    trace = Trace("Hierarchical teams — exercise solution")
    content = Supervisor(MockLLM(content_lead_policy),
                         {"writer": contained(writer), "editor": contained(broken_editor)},
                         {"writer": "drafts", "editor": "edits"}, name="content_lead")
    top = Supervisor(MockLLM(lead([("content_team", "Write the launch headline")], "Launch copy ready (unedited).")),
                     {"content_team": team_as_worker(content, trace=trace)}, {"content_team": "launch copy"}, name="launch_lead")
    r = top.run("Prepare the launch", trace=trace)
    trace.note(f"result: ok={r.ok}; launch_lead saw: {r.turns[0][2]!r}")
    trace.print()
    assert r.ok and "editor unavailable" in r.turns[0][2]


if __name__ == "__main__":
    main()
