"""Human-in-the-loop demo: an agent proposes four actions; policy pauses three; a reviewer
decides later, in a *new* process that reloads the queue from disk.

Run:  python3 code/patterns/human_in_the_loop/main.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.human_in_the_loop.hitl import (  # noqa: E402
    Action, Policy, ReviewQueue, resume, submit_or_execute,
)

POLICY = Policy([
    lambda a: f"refund ${a.payload['amount']} > $100" if a.kind == "refund" and a.payload["amount"] > 100 else None,
    lambda a: "irreversible action" if a.kind == "close_account" else None,
    lambda a: f"low confidence {a.confidence:.2f}" if a.confidence < 0.7 else None,
])

LEDGER: list[str] = []  # the "real world": every side effect lands here


def execute(action: Action) -> str:
    entry = f"{action.kind}({', '.join(f'{k}={v}' for k, v in sorted(action.payload.items()))})"
    LEDGER.append(entry)
    return entry


PROPOSED = [
    Action("refund", {"customer": "sam", "amount": 20}, 0.95),
    Action("refund", {"customer": "lee", "amount": 140}, 0.92),
    Action("close_account", {"customer": "kim"}, 0.97),
    Action("refund", {"customer": "ana", "amount": 35}, 0.55),
]


def main() -> None:
    trace = Trace("Human-in-the-loop")
    with tempfile.TemporaryDirectory() as tmp:
        qpath = pathlib.Path(tmp) / "review_queue.json"

        trace.note("-- process 1 (hour 0): agent proposes actions")
        queue = ReviewQueue(qpath)
        for a in PROPOSED:
            out = submit_or_execute(a, POLICY, queue, execute, context={"ticket": a.payload["customer"]}, now=0)
            rid = f"{out.request_id} " if out.request_id else ""
            trace.step(out.status, f"{a.kind} {a.payload} {rid}{out.detail}")
        del queue  # process exits; only the file remains

        trace.note("-- process 2 (hour 3): reviewer works the queue")
        queue = ReviewQueue(qpath)
        trace.step("pending", ", ".join(queue.pending()))
        queue.decide("R001", "edit", reviewer="maya", edits={"amount": 100}, note="cap at $100")
        queue.decide("R002", "reject", reviewer="maya", note="customer has open dispute")
        for rid in ("R001", "R002", "R001"):  # R001 resumed twice on purpose
            out = resume(queue, rid, execute)
            trace.step(f"resume {rid}", f"{out.status} — {out.detail}")

        trace.note("-- process 3 (hour 30): nobody decided R003")
        queue = ReviewQueue(qpath)
        trace.step("expired", ", ".join(queue.expire(now=30)))
        out = resume(queue, "R003", execute)
        trace.step("resume R003", f"{out.status} — {out.detail}")

    trace.note("ledger: " + " | ".join(LEDGER))
    trace.print()

    assert LEDGER == ["refund(amount=20, customer=sam)", "refund(amount=100, customer=lee)"]


if __name__ == "__main__":
    main()
