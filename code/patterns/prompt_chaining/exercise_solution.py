"""Exercise solution — Prompt chaining.

Task: the draft step sometimes leaks internal ticket IDs (e.g. "JIRA-412") into
customer copy. Add a gate after `draft` that stops the chain when that happens,
without adding any LLM calls.

Run:  python3 code/patterns/prompt_chaining/exercise_solution.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.prompt_chaining.chain import Step, run_chain  # noqa: E402
from patterns.prompt_chaining.main import STEPS  # noqa: E402

INTERNAL_ID = re.compile(r"\b[A-Z]{2,10}-\d+\b")


def no_internal_ids(out: str):
    found = INTERNAL_ID.findall(out)
    return f"internal ticket id(s) leaked: {', '.join(found)}" if found else None


# Same steps, with the new gate attached to `draft`. Steps are data, so this is a one-liner.
SOLUTION_STEPS = [STEPS[0], Step(STEPS[1].name, STEPS[1].template, gate=no_internal_ids), STEPS[2]]

leaky = MockLLM(rules([
    ("USER-FACING", "v2.5\n- Bulk edit for tasks\n- Calendar sync"),
    ("customer announcement", "Version 2.5 brings bulk edit (JIRA-412) and calendar sync (JIRA-418)!"),
    ("social post", "v2.5: bulk edit + calendar sync."),
]))


def main() -> None:
    trace = Trace("Prompt chaining — exercise solution")
    result = run_chain(leaky, SOLUTION_STEPS, "Release 2.5 ...", trace)
    trace.note(f"result: ok={result.ok} stopped_at={result.stopped_at}; calls={leaky.usage.calls}")
    trace.print()
    assert not result.ok and result.stopped_at == "draft" and leaky.usage.calls == 2


if __name__ == "__main__":
    main()
