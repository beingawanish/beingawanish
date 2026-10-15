"""Exercise solution — Critic–reviewer loop.

Task: an author can "fix" one finding and silently break something that already
worked. Give the reviewer memory: any test that passed in an earlier round and fails
now becomes an automatic *blocking* regression finding, named as such.

Run:  python3 code/patterns/critic_reviewer/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.critic_reviewer.main import TESTS, V1, V2, reviewer  # noqa: E402
from patterns.critic_reviewer.review import Finding, Response, review_loop  # noqa: E402

V_REGRESS = ('import unicodedata\n\ndef slugify(s):\n'
             '    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()\n'
             '    return "".join(c for c in s.lower() if c.isalnum())')


def results(code):
    ns: dict = {}
    exec(code, ns)
    return {i: ns["slugify"](i) == o for i, o in TESTS}


class RegressionAwareReviewer:
    def __init__(self, inner):
        self.inner, self.ever_passed = inner, set()

    def __call__(self, code):
        now = results(code)
        regressions = [i for i in self.ever_passed if not now[i]]
        self.ever_passed |= {i for i, ok in now.items() if ok}
        return self.inner(code) + [Finding(f"R{n}", "blocking", f"REGRESSION: {i!r} passed before, fails now")
                                   for n, i in enumerate(sorted(regressions), 1)]


versions = iter([V1, V_REGRESS, V2])


def author(task, current, findings):
    return next(versions), [Response(f.id, "fixed", "addressed") for f in findings]


def main() -> None:
    trace = Trace("Critic–reviewer — exercise solution")
    run = review_loop("Write slugify(s)", author, RegressionAwareReviewer(reviewer), max_rounds=4, trace=trace)
    trace.note(f"result: approved={run.approved} in {run.rounds} rounds")
    trace.print()
    assert run.approved and run.rounds == 3


if __name__ == "__main__":
    main()
