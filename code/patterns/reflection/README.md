# Pattern 8 — Reflection / self-critique

The same model critiques and revises its own output — no external judge.

| | |
|---|---|
| Implementation | [`reflect.py`](reflect.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-2-single-agent/08-reflection.md`](../../../book/part-2-single-agent/08-reflection.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/reflection/main.py
```

## Expected output

```text
Reflection
==========
-- Write Python is_leap(y) for the Gregorian calendar.
[draft] def is_leap(y): …
[critique 1] Missed the Gregorian century rule: 1900 is not a leap year, 2000 is.
[revision 1] def is_leap(y): …
[critique 2] NO ISSUES
measured: first draft 3/4 tests, final 4/4 tests; revisions=1
-- Write Python days_in_month(m, y).
[draft] def days_in_month(m, y): …
[critique 1] NO ISSUES
measured: first draft 3/4 tests, final 3/4 tests; revisions=0
model calls: 6 (same model throughout)
```

> **Reused, not copied:** the deep-research capstone imports this module.

Verified by `python3 code/verify.py reflection`.
