"""Exercise solution — Supervisor.

Task: the supervisor re-reads every worker's full output on every turn, so its prompt
grows with each turn. Cap each history entry's output at N characters (workers keep
full results in shared state) and show the run still finishes with fewer supervisor
prompt tokens. Do not change Supervisor.run().

Run:  python3 code/patterns/supervisor/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.supervisor.main import ROLES, WORKERS, boss  # noqa: E402
from patterns.supervisor.supervisor import Supervisor, SupervisorRun  # noqa: E402

LONG = ("Monthly list prices: Acme (us) $49, Beta $59, Gamma $45. Source notes: "
        + " ".join(["captured from public pricing pages on 2026-10-14"] * 25))


def verbose_researcher(instruction, state):
    WORKERS["researcher"](instruction, state)
    return LONG  # a realistically chatty worker


class BriefingSupervisor(Supervisor):
    def __init__(self, *a, max_chars: int = 80, **kw):
        super().__init__(*a, **kw)
        self.max_chars = max_chars

    def _decide(self, task, run):
        clipped = SupervisorRun(run.ok, run.final,
                                [(w, i, o if len(o) <= self.max_chars else o[: self.max_chars] + "…")
                                 for w, i, o in run.turns])
        return super()._decide(task, clipped)


def main() -> None:
    workers = {**WORKERS, "researcher": verbose_researcher}
    trace = Trace("Supervisor — exercise solution")
    tokens = {}
    for label, cls in (("full history", Supervisor), ("clipped history", BriefingSupervisor)):
        llm = MockLLM(boss)
        r = cls(llm, workers, ROLES).run("Write a one-sentence pricing brief")
        tokens[label] = llm.usage.prompt_tokens
        trace.step(label, f"ok={r.ok} turns={len(r.turns)} supervisor prompt tokens={llm.usage.prompt_tokens}")
    trace.print()
    assert r.ok and tokens["clipped history"] < tokens["full history"] / 2


if __name__ == "__main__":
    main()
