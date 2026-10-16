"""Swarm demo: three peer agents triage bug reports through a blackboard; then a swarm
with one over-eager agent hits the task cap — the failure mode that makes swarms the
last pattern to reach for.

Run:  python3 code/patterns/swarm/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.swarm.swarm import Blackboard, SwarmAgent, run_swarm  # noqa: E402

REPORTS = [
    "Export button crashes on Safari",
    "Please add dark mode",
    "Safari: clicking export crashes the tab",  # same bug as the first report
    "Invoice PDF shows wrong VAT",
]


def triager(prompt, system):
    if "dark mode" in prompt:
        return json.dumps({"result": "feature request → product backlog", "post": []})
    if "Safari" in prompt:  # recognises the duplicate by normalising to the same repro task
        return json.dumps({"result": "bug", "post": [{"kind": "repro", "payload": "export crash on Safari"}]})
    return json.dumps({"result": "bug", "post": [{"kind": "repro", "payload": "VAT on invoice PDF"}]})


def reproducer(prompt, system):
    if "VAT" in prompt:
        return json.dumps({"result": "reproduced: rounding applied before VAT",
                           "post": [{"kind": "estimate", "payload": "VAT rounding fix"}]})
    return json.dumps({"result": "could not reproduce on Safari 18; asked reporter for version", "post": []})


def estimator(prompt, system):
    return json.dumps({"result": "small: 1 day", "post": []})


def eager(prompt, system):  # posts two follow-ups for everything it touches
    topic = prompt.split(": ", 1)[1].split("\n", 1)[0]
    return json.dumps({"result": "partially explored",
                       "post": [{"kind": "explore", "payload": f"{topic}/a"}, {"kind": "explore", "payload": f"{topic}/b"}]})


def main() -> None:
    trace = Trace("Swarm")
    trace.note("-- bug-report swarm (no controller; agents claim by skill)")
    board = Blackboard()
    for r in REPORTS:
        board.post("report", r, "user")
    agents = [SwarmAgent("triager", frozenset({"report"}), MockLLM(triager)),
              SwarmAgent("reproducer", frozenset({"repro"}), MockLLM(reproducer)),
              SwarmAgent("estimator", frozenset({"estimate"}), MockLLM(estimator))]
    r1 = run_swarm(board, agents, trace=trace)
    trace.note(f"result: {r1.stop_reason} after {r1.ticks} ticks; {r1.calls} model calls for {len(REPORTS)} reports; "
               f"duplicate repro tasks suppressed by the board")

    trace.note("-- runaway swarm: an agent that posts 2 follow-ups per task")
    board2 = Blackboard(max_tasks=12)
    board2.post("explore", "pricing", "user")
    r2 = run_swarm(board2, [SwarmAgent(f"explorer{i}", frozenset({"explore"}), MockLLM(eager)) for i in (1, 2)],
                   max_ticks=4)
    trace.note(f"result: {r2.stop_reason}; {r2.calls} calls; tasks={len(board2.tasks)} (cap 12), "
               f"unfinished={r2.unfinished}, posts rejected by cap={board2.rejected}")
    trace.print()

    assert r1.stop_reason == "board empty" and r1.calls == 7
    assert r2.unfinished > 0 and board2.rejected > 0


if __name__ == "__main__":
    main()
