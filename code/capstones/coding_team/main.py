"""Coding-team capstone: a tech lead, a dev team and a QA team ship a --json flag.

Run:  python3 code/capstones/coding_team/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from capstones.coding_team.fixtures import REQUEST, make_models  # noqa: E402
from capstones.coding_team.repo import INITIAL, run_tests  # noqa: E402
from capstones.coding_team.team import CodingTeam  # noqa: E402

BUDGET = 300


def main() -> None:
    files = dict(INITIAL)
    m = make_models()
    trace = Trace("Coding-team capstone", width=110)
    team = CodingTeam(files, m["dev"], m["summarizer"], m["qa"], m["leads"], budget=BUDGET, trace=trace)
    result = team.run(REQUEST)

    final_tests = run_tests(files)
    original_ok = run_tests({**files, **{"test_cli.py": INITIAL["test_cli.py"]}})["failed"] == []
    biggest = max(r.total for r in team.context_log)
    tech_prompts = [c.prompt for c in m["leads"]["tech"].calls]
    leaked = [p for p in tech_prompts if "def " in p or "build_report" in p]
    checks = {
        "all tests pass": (f"passed={final_tests['passed']} failed={len(final_tests['failed'])}",
                           final_tests["failed"] == [] and final_tests["passed"] == 3),
        "text output unchanged": ("original test_cli.py passes unmodified", original_ok),
        "QA approval": (f"approved={team.review_run.approved}, rounds={team.review_run.rounds}",
                        team.review_run.approved),
        "developer context": (f"{len(team.context_log)} prompts, largest {biggest} tokens (budget {BUDGET}), "
                              f"compactions={team.compactions}", biggest <= BUDGET and team.compactions >= 1),
        "tech-lead scoping": (f"{len(tech_prompts)} tech-lead prompts, file contents leaked into {len(leaked)}",
                              not leaked),
    }
    trace.note("-- acceptance")
    trace.note(f"tech lead: {result.stop_reason}; files now: {sorted(files)}")
    for name, (detail, ok) in checks.items():
        trace.step("PASS" if ok else "FAIL", f"{name}: {detail}")
    calls = {"developer": m["dev"].usage.calls, "summarizer": m["summarizer"].usage.calls, "qa": m["qa"].usage.calls,
             **{f"{k}-lead": v.usage.calls for k, v in m["leads"].items()}}
    trace.note("model calls: " + ", ".join(f"{k}={v}" for k, v in calls.items()))
    trace.print()
    assert all(ok for _, ok in checks.values()), "acceptance criteria failed"


if __name__ == "__main__":
    main()
