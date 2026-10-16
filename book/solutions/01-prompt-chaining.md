# Solution — 1. Prompt chaining

**Exercise.** Stop the chain when the draft leaks internal ticket IDs, without adding model calls.

**Approach.** A gate is a plain function returning `None` (pass) or a reason. Attach one to the `draft` step. Because steps are data, the rest of the chain is reused unchanged:

```python
INTERNAL_ID = re.compile(r"\b[A-Z]{2,10}-\d+\b")

def no_internal_ids(out: str):
    found = INTERNAL_ID.findall(out)
    return f"internal ticket id(s) leaked: {', '.join(found)}" if found else None

SOLUTION_STEPS = [STEPS[0], Step(STEPS[1].name, STEPS[1].template, gate=no_internal_ids), STEPS[2]]
```

Run: `python3 code/patterns/prompt_chaining/exercise_solution.py`

<!-- expected-output: code/patterns/prompt_chaining/exercise_solution.py -->
```text
Prompt chaining — exercise solution
===================================
[extract] v2.5 | - Bulk edit for tasks | - Calendar sync
[gate:extract] pass
[draft] Version 2.5 brings bulk edit (JIRA-412) and calendar sync (JIRA-418)!
[gate:draft] STOP — internal ticket id(s) leaked: JIRA-412, JIRA-418
result: ok=False stopped_at=draft; calls=2
```

**Answer.** The stopped run costs **two** calls (extract, draft). `compress` never runs.

**Discussion.** The regex is deliberately narrow (`PROJ-123` style). It could also match legitimate product codes such as `ISO-9001`. In production, keep an allow-list or match only your tracker's project keys. A gate's false positives are cheap here (the run stops and someone looks), which is why a simple rule is acceptable. Where a false positive is expensive, prefer a repair step ([#11](../part-2-single-agent/11-guardrailed-generation.md)) over a hard stop.
