"""Exercise solution — Debate.

Task: judges can be swayed by *order* (favouring whoever spoke last) rather than by
arguments. Detect it: run the judge twice with the debaters' order swapped. If the
decisions differ, the verdict is order-sensitive and must be escalated, not trusted.

Run:  python3 code/patterns/debate/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.debate.debate import Debater, debate  # noqa: E402
from patterns.debate.main import Q_SPLIT, con, judge, pro  # noqa: E402


def recency_biased_judge(prompt, system):
    last_speaker = [ln for ln in prompt.splitlines() if ln.startswith("[r")][-1].split()[1].rstrip(":")
    side = "Split now" if last_speaker == "pro" else "Do not split yet"
    return json.dumps({"decision": side, "rationale": f"The final argument (by {last_speaker}) was most convincing."})


def order_robust(judge_llm, debaters, question):
    a = debate(debaters, judge_llm, question)
    b = debate(list(reversed(debaters)), judge_llm, question)
    return a.decision == b.decision, a.decision, b.decision


def main() -> None:
    debaters = [Debater("pro", MockLLM(pro), "argue FOR"), Debater("con", MockLLM(con), "argue AGAINST")]
    trace = Trace("Debate — exercise solution")
    for label, j in (("argument-based judge", judge), ("recency-biased judge", MockLLM(recency_biased_judge))):
        stable, d1, d2 = order_robust(j, debaters, Q_SPLIT)
        trace.step(label, f"order-stable={stable}" + ("" if stable else f" ('{d1}' vs '{d2}') → escalate"))
    trace.print()
    assert order_robust(judge, debaters, Q_SPLIT)[0]
    assert not order_robust(MockLLM(recency_biased_judge), debaters, Q_SPLIT)[0]


if __name__ == "__main__":
    main()
