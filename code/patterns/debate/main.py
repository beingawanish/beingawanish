"""Debate demo: an architecture decision argued over two rounds and judged; a second
question where the peers agree in round 1 and the judge is never called.

Run:  python3 code/patterns/debate/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.debate.debate import Debater, debate  # noqa: E402

Q_SPLIT = "Should we split billing out of the monolith this quarter?"
Q_INDEX = "Should we add an index on orders.customer_id (queries scan 4M rows)?"


def pro(prompt, system):
    if "index" in prompt:
        return json.dumps({"argument": "Yes: every lookup scans 4M rows; the index is cheap to add online.",
                           "agree_with_opponents": True})
    if "round 2" in prompt:
        return json.dumps({"argument": "Ownership is solvable by assigning two engineers; deploy coupling costs us "
                                       "a blocked release every sprint.", "agree_with_opponents": False})
    return json.dumps({"argument": "Yes: billing deploys are blocked by unrelated monolith releases twice a month.",
                       "agree_with_opponents": False})


def con(prompt, system):
    if "index" in prompt:
        return json.dumps({"argument": "Yes from me too: the write overhead is negligible next to the read savings.",
                           "agree_with_opponents": True})
    if "round 2" in prompt:
        return json.dumps({"argument": "Billing shares 14 tables with orders; splitting now means distributed "
                                       "transactions before we have an API boundary.", "agree_with_opponents": False})
    return json.dumps({"argument": "No: no team owns billing today, so a new service would be orphaned.",
                       "agree_with_opponents": False})


judge = MockLLM(lambda p, s: json.dumps({
    "decision": "Not this quarter: first put billing behind an internal API inside the monolith, then split.",
    "rationale": "Con's shared-tables point (r2) makes a split now risky; Pro's deploy-blocking cost (r1) is real, "
                 "so the API boundary should start now to enable the split next quarter."}), name="judge")


def main() -> None:
    debaters = [Debater("pro", MockLLM(pro), "argue FOR"), Debater("con", MockLLM(con), "argue AGAINST")]
    trace = Trace("Debate")
    trace.note(f"-- {Q_SPLIT}")
    r1 = debate(debaters, judge, Q_SPLIT, rounds=2, trace=trace)
    trace.note(f"result: consensus={r1.consensus}, rounds={r1.rounds}")
    trace.note(f"-- {Q_INDEX}")
    r2 = debate(debaters, judge, Q_INDEX, rounds=2, trace=trace)
    trace.note(f"result: consensus={r2.consensus}, rounds={r2.rounds}; judge calls in total: {judge.usage.calls}")
    trace.print()

    assert not r1.consensus and r1.decision.startswith("Not this quarter")
    assert r2.consensus and r2.rounds == 1 and judge.usage.calls == 1


if __name__ == "__main__":
    main()
