"""Exercise solution — Plan-and-execute.

Task: re-planning costs a large-model call. When an availability check fails and
the earlier search already returned other venues, the fix is mechanical: retry
availability for the next candidate and swap that venue into the remaining steps.
Implement it as a `repair` hook and count the planner calls saved.

Run:  python3 code/patterns/plan_and_execute/exercise_solution.py
"""

import pathlib
import sys
from dataclasses import replace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.plan_and_execute.main import ACTIONS, GOAL, execute, planner_model  # noqa: E402
from patterns.plan_and_execute.planner import Step, plan_and_execute  # noqa: E402


def next_venue_repair(step, result, remaining, results):
    if step.action != "check_availability":
        return None
    candidates = next((r.output for r in results.values() if isinstance(r.output, list)), [])
    tried = {r.note.removesuffix(" unavailable") for r in results.values() if r.note.endswith("unavailable")}
    nxt = next((v for v in candidates if v not in tried), None)
    if nxt is None:
        return None  # nothing local to try: let the planner think
    old = step.args["venue"]
    retry = Step(step.id + "r", "check_availability", {**step.args, "venue": nxt}, "local repair")
    swapped = [replace(s, id=s.id + "r", args={k: (nxt if v == old else v) for k, v in s.args.items()})
               for s in remaining]
    return [retry, *swapped]


def main() -> None:
    planner = MockLLM(planner_model)
    trace = Trace("Plan-and-execute — exercise solution")
    run = plan_and_execute(planner, GOAL, ACTIONS, execute, trace=trace, repair=next_venue_repair)
    trace.note(f"result: {run.stop_reason}; replans={run.replans}; planner calls={planner.usage.calls} (was 2)")
    trace.print()
    assert run.ok and run.replans == 0 and planner.usage.calls == 1
    assert "Quinta Verde" in run.results["s4r"].output


if __name__ == "__main__":
    main()
