# Pattern 7 — Plan-and-execute

Write an explicit plan, execute it step by step, re-plan when results invalidate it.

| | |
|---|---|
| Implementation | [`planner.py`](planner.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-2-single-agent/07-plan-and-execute.md`](../../../book/part-2-single-agent/07-plan-and-execute.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/plan_and_execute/main.py
```

## Expected output

```text
Plan-and-execute
================
[plan v1] s1:search_venues → s2:check_availability → s3:get_quote → s4:draft_invite
[exec s1] ok  ['Casa Azul', 'Quinta Verde']
[exec s2] FAIL booked (Casa Azul unavailable)
[plan v2] s2b:check_availability → s3b:get_quote → s4b:draft_invite
[exec s2b] ok  free
[exec s3b] ok  EUR 1800
[exec s4b] ok  Invite: offsite at Quinta Verde on 14 Nov
result: completed; plans written=2, replans=1, steps executed=5, planner calls=2
final: Invite: offsite at Quinta Verde on 14 Nov
```

> **Reused, not copied:** the deep-research capstone imports this module.

Verified by `python3 code/verify.py plan_and_execute`.
