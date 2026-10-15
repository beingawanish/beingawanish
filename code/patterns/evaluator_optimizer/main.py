"""Evaluator-optimizer demo: an apology email that converges, and a task that stalls.

Run:  python3 code/patterns/evaluator_optimizer/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.evaluator_optimizer.optimizer import optimize  # noqa: E402

RUBRIC = [
    "Acknowledges the specific order and delay",
    "Offers a concrete remedy (amount, date, or action)",
    "Does not blame the customer or a third party",
    "Under 60 words",
]

APOLOGY = "Apology to Sam: order #4471 arrived 6 days late"
PROMISE = "Reply to Lee promising same-day delivery tomorrow"

V1 = "Hi Sam, sorry order #4471 was late — the courier had problems. We'll make it up to you somehow."
V2 = "Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. We'll make it up to you."
V3 = ("Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. I've refunded your $9.99 "
      "shipping fee today and added free express shipping to your next order.")

generator = MockLLM(rules([
    (lambda p, s: "Lee" in p, "Hi Lee, we guarantee same-day delivery tomorrow!"),
    # Like real models, this one fixes feedback partially: one issue per revision.
    (lambda p, s: "That's on us" in p, V3),        # revising V2 -> adds the concrete remedy
    (lambda p, s: "courier" in p, V2),             # revising V1 -> drops the blame only
    (lambda p, s: p.startswith("WRITE:"), V1),     # first draft
]))


def judge(prompt, system):
    if "Lee" in prompt:
        return '{"pass": false, "feedback": ["Same-day delivery cannot be guaranteed; do not promise it"]}'
    draft = prompt.split("Draft:\n", 1)[1]
    fb = []
    if "courier" in draft:
        fb.append("Remove blame on the courier; take ownership")
    if "somehow" in draft or "make it up to you." in draft:
        fb.append("Offer a concrete remedy, e.g. refund the shipping fee")
    return '{"pass": %s, "feedback": [%s]}' % (
        "false" if fb else "true", ", ".join(f'"{f}"' for f in fb))


evaluator = MockLLM(judge, name="evaluator")


def main() -> None:
    trace = Trace("Evaluator-optimizer")
    trace.note(f"-- {APOLOGY}")
    r1 = optimize(generator, evaluator, APOLOGY, RUBRIC, max_rounds=4, trace=trace)
    trace.note(f"result: passed={r1.passed} rounds={r1.rounds} stop={r1.stop_reason}")
    trace.note(f"-- {PROMISE}")
    r2 = optimize(generator, evaluator, PROMISE, RUBRIC, max_rounds=4, trace=trace)
    trace.note(f"result: passed={r2.passed} rounds={r2.rounds} stop={r2.stop_reason} -> escalate to a human")
    trace.note(f"total model calls: {generator.usage.calls + evaluator.usage.calls}")
    trace.print()

    assert r1.passed and r1.rounds == 3 and len(r1.output.split()) < 60
    assert not r2.passed and r2.stop_reason == "stalled" and r2.rounds == 2


if __name__ == "__main__":
    main()
