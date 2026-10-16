"""Exercise solution — Swarm.

Task: an agent crashes right after claiming a task. With no controller, nobody
notices: the task stays "claimed" forever and the swarm stalls. Add claim *leases*:
a claim that is not completed within N board operations expires and the task
reopens for any capable agent.

Run:  python3 code/patterns/swarm/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.swarm.swarm import Blackboard, SwarmAgent, run_swarm  # noqa: E402


class LeaseBoard(Blackboard):
    def __init__(self, lease: int = 1, **kw):
        super().__init__(**kw)
        self.lease, self.clock, self.claimed_at, self.expired = lease, 0, {}, []

    def claim(self, agent):
        self.clock += 1
        for t in self.tasks:  # reopen stale claims before looking for work
            if t.status == "claimed" and self.clock - self.claimed_at.get(t.id, self.clock) > self.lease:
                t.status, t.claimed_by = "open", None
                self.expired.append(t.id)
        task = super().claim(agent)
        if task:
            self.claimed_at[task.id] = self.clock
        return task


def worker(prompt, system):
    return json.dumps({"result": "labelled", "post": []})


def main() -> None:
    trace = Trace("Swarm — exercise solution")
    for label, board in (("plain board", Blackboard()), ("lease board", LeaseBoard(lease=1))):
        for i in range(3):
            board.post("label", f"ticket {i}", "user")
        board.claim(SwarmAgent("crashed", frozenset({"label"}), MockLLM(worker)))  # claims T1, then dies
        r = run_swarm(board, [SwarmAgent("labeller", frozenset({"label"}), MockLLM(worker))], max_ticks=8)
        extra = f", expired claims={board.expired}" if isinstance(board, LeaseBoard) else ""
        trace.step(label, f"{r.stop_reason}; done={r.done}, unfinished={r.unfinished}{extra}")
    trace.print()
    assert r.stop_reason == "board empty"


if __name__ == "__main__":
    main()
