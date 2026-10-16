"""Eval harness demo: a keyword classifier (v1) vs an LLM classifier (v2) on ten fixed cases.

v2 wins on average — and still gets blocked, because it regresses a critical case.

Run:  python3 code/patterns/eval_harness/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, extract_json, rules  # noqa: E402
from patterns.eval_harness.harness import (  # noqa: E402
    Case, at_most, compare, field_equals, format_comparison, format_report, run_eval,
)

CASES = [
    Case("c01", "I was charged twice this month", {"route": "billing"}, ("critical",)),
    Case("c02", "App crashes when I open settings", {"route": "technical"}),
    Case("c03", "Reset my password please", {"route": "account"}, ("critical",)),
    Case("c04", "Refund my annual plan", {"route": "billing"}),
    Case("c05", "Error 500 on the payment page", {"route": "technical"}),
    Case("c06", "Can't sign in after changing email", {"route": "account"}),
    Case("c07", "Do you have a public API?", {"route": "general"}),
    Case("c08", "Invoice shows the wrong company name", {"route": "billing"}, ("critical",)),
    Case("c09", "My card was declined at renewal", {"route": "billing"}),
    Case("c10", "The dashboard is painfully slow", {"route": "technical"}),
]


# v1: ordered keyword rules — free, fast, brittle.
def classify_v1(text: str) -> dict:
    low = text.lower()
    for route, words in [("billing", ["charged", "refund", "invoice", "payment"]),
                         ("technical", ["crash", "error"]),
                         ("account", ["password", "email"])]:
        if any(w in low for w in words):
            return {"route": route, "llm_calls": 0}
    return {"route": "general", "llm_calls": 0}


# v2: an LLM classifier. The mock encodes how this particular model behaves on each case.
v2_model = MockLLM(rules([
    ("charged twice", '{"route": "billing"}'), ("crashes", '{"route": "technical"}'),
    ("password", '{"route": "account"}'), ("refund", '{"route": "billing"}'),
    ("error 500", '{"route": "technical"}'), ("sign in", '{"route": "account"}'),
    ("public api", '{"route": "general"}'),
    ("company name", '{"route": "account"}'),  # the model thinks "company name" is a profile edit
    ("declined", '{"route": "billing"}'), ("slow", '{"route": "technical"}'),
]))


def classify_v2(text: str) -> dict:
    return {"route": extract_json(v2_model.complete(f"Classify: {text}"))["route"], "llm_calls": 1}


SCORERS = [field_equals("route"), at_most("llm_calls", 1)]


def main() -> None:
    v1 = run_eval("v1 keywords", classify_v1, CASES, SCORERS)
    v2 = run_eval("v2 llm", classify_v2, CASES, SCORERS)
    trace = Trace("Eval harness")
    trace.note(format_report(v1, tags=("critical",)))
    trace.note(format_report(v2, tags=("critical",)))
    cmp = compare(v1, v2)
    trace.note(format_comparison(cmp))
    trace.print()

    assert v1.mean("route_correct") == 0.7 and v2.mean("route_correct") == 0.9
    assert cmp.verdict.startswith("BLOCK") and ("c08", "route_correct", True) in cmp.regressions


if __name__ == "__main__":
    main()
