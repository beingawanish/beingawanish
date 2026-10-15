"""Exercise solution — Human-in-the-loop.

Task: add *dual control*: refunds above $500 need approvals from two different
reviewers before they can execute. A single approval leaves the request pending;
the same reviewer approving twice does not count twice; one rejection rejects.

Run:  python3 code/patterns/human_in_the_loop/exercise_solution.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.human_in_the_loop.hitl import Action, Policy, ReviewQueue, resume, submit_or_execute  # noqa: E402


class DualControlQueue(ReviewQueue):
    def __init__(self, path, threshold: float = 500):
        super().__init__(path)
        self.threshold = threshold

    def decide(self, rid, verdict, reviewer, edits=None, note=""):
        req = self.get(rid)
        needs_two = req["action"]["kind"] == "refund" and req["action"]["payload"]["amount"] > self.threshold
        if not needs_two or verdict == "reject":
            return super().decide(rid, verdict, reviewer, edits, note)
        approvals = req.setdefault("approvals", [])
        if reviewer not in approvals:
            approvals.append(reviewer)
        self._save()
        if len(approvals) >= 2:
            super().decide(rid, verdict, reviewer, edits, f"approved by {' + '.join(approvals)}")


LEDGER = []


def execute(a):
    LEDGER.append(f"{a.kind} ${a.payload['amount']}")
    return LEDGER[-1]


def main() -> None:
    trace = Trace("Human-in-the-loop — exercise solution")
    policy = Policy([lambda a: "refund > $100" if a.payload["amount"] > 100 else None])
    with tempfile.TemporaryDirectory() as tmp:
        q = DualControlQueue(pathlib.Path(tmp) / "q.json")
        rid = submit_or_execute(Action("refund", {"amount": 900}), policy, q, execute, {}, now=0).request_id
        for reviewer in ("maya", "maya", "omar"):
            q.decide(rid, "approve", reviewer)
            trace.step(f"{reviewer} approves", f"status={q.get(rid)['status']} approvals={q.get(rid).get('approvals')}")
        trace.step("resume", resume(q, rid, execute).status)
    trace.note(f"ledger: {LEDGER}")
    trace.print()
    assert LEDGER == ["refund $900"]


if __name__ == "__main__":
    main()
