"""Exercise solution — Parallelization.

Task: in the voting demo, judge C's vote was unusable, so the verdict rested on 2 of 3
judges with "agreement 1.00" — overstated. Add a quorum: require at least 3 usable
votes, otherwise return no verdict (escalate).

Run:  python3 code/patterns/parallelization/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.parallelization.fanout import majority_vote  # noqa: E402


def vote_with_quorum(votes, cast: int, quorum: int):
    """Agreement is measured against votes *cast*, not just usable ones."""
    if len(votes) < quorum:
        return None, f"no quorum ({len(votes)}/{cast} usable, need {quorum})"
    winner, _ = majority_vote(votes)
    agreement = votes.count(winner) / cast if winner else 0.0
    return winner, f"agreement {agreement:.2f} of {cast} cast"


def main() -> None:
    trace = Trace("Parallelization — exercise solution")
    for label, votes, cast in [("2 usable of 3", ["PHISHING", "PHISHING"], 3),
                               ("3 usable of 3", ["PHISHING", "PHISHING", "SAFE"], 3)]:
        winner, why = vote_with_quorum(votes, cast, quorum=3)
        trace.step(label, f"verdict={winner} — {why}")
    trace.print()
    assert vote_with_quorum(["PHISHING", "PHISHING"], 3, 3)[0] is None
    assert vote_with_quorum(["PHISHING", "PHISHING", "SAFE"], 3, 3)[0] == "PHISHING"


if __name__ == "__main__":
    main()
