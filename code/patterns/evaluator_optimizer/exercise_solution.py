"""Exercise solution — Evaluator-optimizer.

Task: the rubric's "under 60 words" criterion is checkable in code. Put a free
deterministic pre-check in front of the evaluator so over-long drafts are rejected
without spending an evaluator call. Count the evaluator calls saved.

Run:  python3 code/patterns/evaluator_optimizer/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.evaluator_optimizer.main import RUBRIC, evaluator  # noqa: E402
from patterns.evaluator_optimizer.optimizer import optimize  # noqa: E402


class PrecheckedEvaluator:
    """Wraps the evaluator LLM; answers deterministically when a cheap check already fails."""

    def __init__(self, inner, max_words: int):
        self.inner, self.max_words, self.short_circuits = inner, max_words, 0

    def complete(self, prompt, system=""):
        draft = prompt.split("Draft:\n", 1)[1].split("\n\nReply", 1)[0]
        words = len(draft.split())
        if words >= self.max_words:
            self.short_circuits += 1
            return json.dumps({"pass": False, "feedback": [f"Cut to under {self.max_words} words (now {words})"]})
        return self.inner.complete(prompt, system)


LONG = ("Hi Sam, I am so incredibly sorry to hear that your order #4471 arrived six whole days later than "
        "we promised. I completely understand how frustrating it must have been to wait, especially after you "
        "had planned around the original delivery date. That's on us, and we take it seriously. I've refunded "
        "your $9.99 shipping fee today, and our whole team is reviewing what went wrong so it never happens again.")
SHORT = ("Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. I've refunded your $9.99 "
         "shipping fee today.")
writer = MockLLM(rules([(lambda p, s: "Cut to under" in p, SHORT), (lambda p, s: True, LONG)]))


def main() -> None:
    trace = Trace("Evaluator-optimizer — exercise solution")
    gated = PrecheckedEvaluator(evaluator, max_words=60)
    before = evaluator.usage.calls
    result = optimize(writer, gated, "Apology to Sam: order #4471 arrived 6 days late", RUBRIC, trace=trace)
    trace.note(f"passed={result.passed} rounds={result.rounds}; evaluator calls={evaluator.usage.calls - before}, "
               f"saved by pre-check={gated.short_circuits}")
    trace.print()
    assert result.passed and gated.short_circuits == 1 and evaluator.usage.calls - before == 1


if __name__ == "__main__":
    main()
