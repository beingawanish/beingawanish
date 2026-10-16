# Pattern 20 — Context management

Budget each call's context: pin, progressively disclose, compact, evict.

| | |
|---|---|
| Implementation | [`context.py`](context.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-4-cross-cutting/20-context-management.md`](../../../book/part-4-cross-cutting/20-context-management.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/context_management/main.py
```

## Expected output

```text
Context management
==================
-- call 1: nothing loaded yet
[naive prompt] 924 tokens
[managed prompt] 190 tokens (budget 300): system=20, task=12, tools=77, summary=29, recent=31, docs=21
[compacted] 5 old turns → 1 summary (1 summarizer call)
[evicted] postmortem-2025 (relevance 0.40), style-guide (relevance 0.10)
-- call 2: the model asked help(deploy); two more turns happened
[managed prompt] 285 tokens: system=20, task=12, tools=187, summary=29, recent=16, docs=21
[evicted] postmortem-2025 (relevance 0.40), style-guide (relevance 0.10)
[progressive disclosure] full docs loaded for ['deploy']; other 5 tools stay one-liners
[compacted] 7 turns folded in total; summarizer calls=2 (incremental)
[pinned + recalled] rule present=True, CHG-881 present=True, INC-4411 present=True
```

> **Reused, not copied:** the coding-team capstone imports this module.

Verified by `python3 code/verify.py context_management`.
