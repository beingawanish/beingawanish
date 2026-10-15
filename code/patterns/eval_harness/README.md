# Pattern 21 — Eval harness

Fixed cases + scorers → report; per-case comparison decides ship or block.

| | |
|---|---|
| Implementation | [`harness.py`](harness.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | — (with its chapter) |
| Chapter | [`book/part-4-cross-cutting/21-eval-harness.md`](../../../book/part-4-cross-cutting/21-eval-harness.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/eval_harness/main.py
```

## Expected output

```text
Eval harness
============
v1 keywords:
  route_correct    0.70  [critical] 1.00  fails: c05, c09, c10
  llm_calls<=1     1.00  [critical] 1.00  fails: -
v2 llm:
  route_correct    0.90  [critical] 0.67  fails: c08
  llm_calls<=1     1.00  [critical] 1.00  fails: -
comparison:
  route_correct    0.70 -> 0.90 (+0.20)
  llm_calls<=1     1.00 -> 1.00 (+0.00)
  fixed:      c05/route_correct, c09/route_correct, c10/route_correct
  regressed:  c08/route_correct (critical)
  verdict:    BLOCK — 1 critical regression(s)
```

> **Reused, not copied:** the support-triage capstone imports this module.

Verified by `python3 code/verify.py eval_harness`.
