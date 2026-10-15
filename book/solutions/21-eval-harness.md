# Solution — 21. Eval harness

**Exercise.** Express the acceptance policy as data, including tag slices.

**Approach.** A threshold key is `scorer` or `scorer@tag`. The gate computes each mean, using the tag slice where one is named, and returns a list of failures. An empty list means pass.

```python
def gate(report, thresholds: dict[str, float]) -> list[str]:
    failures = []
    for key, bar in thresholds.items():
        scorer, _, tag = key.partition("@")
        value = report.mean(scorer, tag or None)
        if value < bar:
            failures.append(f"{key} {value:.2f} < {bar:.2f}")
    return failures

THRESHOLDS = {"route_correct": 0.85, "route_correct@critical": 1.0, "llm_calls<=1": 1.0}
```

Run: `python3 code/patterns/eval_harness/exercise_solution.py`

<!-- expected-output: code/patterns/eval_harness/exercise_solution.py -->
```text
Eval harness — exercise solution
================================
[v1] FAIL: route_correct 0.70 < 0.85
[v2] FAIL: route_correct@critical 0.67 < 1.00
[v3] PASS
```

**Discussion.** v1 fails on overall accuracy, v2 on the critical slice, and v3 passes both. The v3 fix (a keyword override for "invoice") came from reading the per-case report, which is the harness doing its real job: pointing at the exact case to fix. Keep thresholds in version control next to the cases, so that changing a bar is a reviewed change, not a quiet edit.
