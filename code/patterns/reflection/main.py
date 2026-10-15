"""Reflection demo: a self-critique that catches a real bug, and one that misses one.

Tests are run only to *measure* the drafts — they are not part of the loop (that
would make it an evaluator, not reflection).

Run:  python3 code/patterns/reflection/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.reflection.reflect import reflect  # noqa: E402

LEAP_V1 = "def is_leap(y):\n    return y % 4 == 0"
LEAP_V2 = "def is_leap(y):\n    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)"
DAYS_V1 = ("def days_in_month(m, y):\n"
           "    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]")

model = MockLLM(rules([
    # is_leap: the critique spots the century rule.
    (lambda p, s: "is_leap" in p and "REVISE" in p, LEAP_V2),
    (lambda p, s: "is_leap" in p and "CRITIQUE" in p and "400" in p, "NO ISSUES"),
    (lambda p, s: "is_leap" in p and "CRITIQUE" in p,
     "Missed the Gregorian century rule: 1900 is not a leap year, 2000 is."),
    (lambda p, s: "is_leap" in p, LEAP_V1),
    # days_in_month: the model's blind spot — it believes its table is complete.
    (lambda p, s: "days_in_month" in p and "CRITIQUE" in p, "NO ISSUES"),
    (lambda p, s: "days_in_month" in p, DAYS_V1),
]))

TESTS = {
    "is_leap": [((2024,), True), ((2023,), False), ((1900,), False), ((2000,), True)],
    "days_in_month": [((1, 2023), 31), ((4, 2023), 30), ((2, 2023), 28), ((2, 2024), 29)],
}


def score(src: str, fn: str) -> str:
    ns: dict = {}
    exec(src, ns)  # our own deterministic strings, never model output from the network
    passed = sum(ns[fn](*args) == want for args, want in TESTS[fn])
    return f"{passed}/{len(TESTS[fn])} tests"


def main() -> None:
    trace = Trace("Reflection")
    results = {}
    for fn, task in [("is_leap", "Write Python is_leap(y) for the Gregorian calendar."),
                     ("days_in_month", "Write Python days_in_month(m, y).")]:
        trace.note(f"-- {task}")
        r = reflect(model, task, trace=trace)
        results[fn] = r
        trace.note(f"measured: first draft {score(r.first_draft, fn)}, final {score(r.output, fn)}; revisions={r.rounds}")
    trace.note(f"model calls: {model.usage.calls} (same model throughout)")
    trace.print()

    assert score(results["is_leap"].output, "is_leap") == "4/4 tests"
    assert results["days_in_month"].rounds == 0  # the blind spot: self-critique approved a bug
    assert score(results["days_in_month"].output, "days_in_month") == "3/4 tests"


if __name__ == "__main__":
    main()
