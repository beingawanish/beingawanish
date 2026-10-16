"""Exercise solution — Eval harness.

Task: v2 improves the mean but breaks a critical case, and `compare()` catches it.
Turn the acceptance policy into data: write `gate(report, thresholds)` where
thresholds may name a tag slice ("route_correct@critical": 1.0). Show that v1
fails the overall bar, v2 fails the critical-slice bar, and a v3 that fixes c08
passes both.

Run:  python3 code/patterns/eval_harness/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.eval_harness.harness import run_eval  # noqa: E402
from patterns.eval_harness.main import CASES, SCORERS, classify_v1, classify_v2  # noqa: E402


def gate(report, thresholds: dict[str, float]) -> list[str]:
    failures = []
    for key, bar in thresholds.items():
        scorer, _, tag = key.partition("@")
        value = report.mean(scorer, tag or None)
        if value < bar:
            failures.append(f"{key} {value:.2f} < {bar:.2f}")
    return failures


def classify_v3(text):
    out = classify_v2(text)
    if "invoice" in text.lower():  # targeted fix for the c08 confusion, found via the per-case report
        out["route"] = "billing"
    return out


THRESHOLDS = {"route_correct": 0.85, "route_correct@critical": 1.0, "llm_calls<=1": 1.0}


def main() -> None:
    trace = Trace("Eval harness — exercise solution")
    for name, system in (("v1", classify_v1), ("v2", classify_v2), ("v3", classify_v3)):
        fails = gate(run_eval(name, system, CASES, SCORERS), THRESHOLDS)
        trace.step(name, "PASS" if not fails else "FAIL: " + "; ".join(fails))
    trace.print()
    assert gate(run_eval("v3", classify_v3, CASES, SCORERS), THRESHOLDS) == []


if __name__ == "__main__":
    main()
