# Pattern 9 — Tool-use loop

Structured tool calls, host-side validation and execution, explicit stop conditions.

| | |
|---|---|
| Implementation | [`loop.py`](loop.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-2-single-agent/09-tool-use-loop.md`](../../../book/part-2-single-agent/09-tool-use-loop.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/tool_use_loop/main.py
```

## Expected output

```text
Tool-use loop
=============
-- Book a 30-minute sync with Dana tomorrow afternoon (2026-10-16)
[call 1] list_events({"date": 20261016})
[result 1] ERROR: list_events: argument 'date' must be str
[call 2] list_events({"date": "2026-10-16"})
[result 2] [{"title": "Design review", "start": "13:00", "end": "14:00"}]
[call 3] create_event({"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"})
[result 3] {"created": true, "title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}
[final] Booked Sync with Dana on 2026-10-16, 14:00-14:30 (after your design review).
result: final in 4 steps; confirmations asked: ['create_event']
-- Summarise my week
[call 1] list_events({"date": "2026-10-16"})
[result 1] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[call 2] list_events({"date": "2026-10-16"})
[result 2] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[call 3] list_events({"date": "2026-10-16"})
[result 3] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[stop] step limit 3 reached
result: max_steps, final=None
```

> **Reused, not copied:** the coding-team capstone imports this module.

Verified by `python3 code/verify.py tool_use_loop`.
