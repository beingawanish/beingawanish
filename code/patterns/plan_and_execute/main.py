"""Plan-and-execute demo: book a team offsite. The first-choice venue turns out to be
unavailable, the planner re-plans around it, and execution finishes.

Run:  python3 code/patterns/plan_and_execute/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.plan_and_execute.planner import StepResult, plan_and_execute  # noqa: E402

GOAL = "Offsite in Porto for 12 people on 14 Nov, under EUR 2000, then draft the invite"
ACTIONS = {
    "search_venues": "list venues in a city for N people (args: city, people)",
    "check_availability": "is a venue free on a date (args: venue, date)",
    "get_quote": "price for a venue (args: venue, people)",
    "draft_invite": "write the invitation (args: venue, date)",
}

# The world. Tools are plain functions: the executor needs no model at all.
VENUES = ["Casa Azul", "Quinta Verde"]
BOOKED = {("Casa Azul", "14 Nov")}
PRICES = {"Casa Azul": 1500, "Quinta Verde": 1800}


def execute(step, results) -> StepResult:
    a = step.args
    if step.action == "search_venues":
        return StepResult(True, VENUES)
    if step.action == "check_availability":
        free = (a["venue"], a["date"]) not in BOOKED
        return StepResult(free, "free" if free else "booked", "" if free else f"{a['venue']} unavailable")
    if step.action == "get_quote":
        price = PRICES[a["venue"]]
        return StepResult(price <= 2000, f"EUR {price}")
    if step.action == "draft_invite":
        return StepResult(True, f"Invite: offsite at {a['venue']} on {a['date']}")
    return StepResult(False, None, "unknown action")


PLAN_1 = [
    {"id": "s1", "action": "search_venues", "args": {"city": "Porto", "people": 12}, "purpose": "candidates"},
    {"id": "s2", "action": "check_availability", "args": {"venue": "Casa Azul", "date": "14 Nov"}, "purpose": "top pick"},
    {"id": "s3", "action": "get_quote", "args": {"venue": "Casa Azul", "people": 12}, "purpose": "budget"},
    {"id": "s4", "action": "draft_invite", "args": {"venue": "Casa Azul", "date": "14 Nov"}, "purpose": "invite"},
]
PLAN_2 = [
    {"id": "s2b", "action": "check_availability", "args": {"venue": "Quinta Verde", "date": "14 Nov"}, "purpose": "next pick"},
    {"id": "s3b", "action": "get_quote", "args": {"venue": "Quinta Verde", "people": 12}, "purpose": "budget"},
    {"id": "s4b", "action": "draft_invite", "args": {"venue": "Quinta Verde", "date": "14 Nov"}, "purpose": "invite"},
]


def planner_model(prompt, system):
    if prompt.startswith("REPLAN") and "Casa Azul unavailable" in prompt:
        return json.dumps(PLAN_2)
    return json.dumps(PLAN_1)


def main() -> None:
    planner = MockLLM(planner_model, name="large-planner")
    trace = Trace("Plan-and-execute")
    run = plan_and_execute(planner, GOAL, ACTIONS, execute, trace=trace)
    trace.note(f"result: {run.stop_reason}; plans written={len(run.plans)}, replans={run.replans}, "
               f"steps executed={len(run.results)}, planner calls={planner.usage.calls}")
    trace.note("final: " + run.results["s4b"].output)
    trace.print()

    assert run.ok and run.replans == 1 and "Quinta Verde" in run.results["s4b"].output
    assert "s3" not in run.results  # the stale steps of plan v1 were never executed


if __name__ == "__main__":
    main()
