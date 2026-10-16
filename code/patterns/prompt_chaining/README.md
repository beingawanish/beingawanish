# Pattern 1 — Prompt chaining

A fixed, linear sequence of LLM calls with code gates between steps.

| | |
|---|---|
| Implementation | [`chain.py`](chain.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-1-workflow/01-prompt-chaining.md`](../../../book/part-1-workflow/01-prompt-chaining.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/prompt_chaining/main.py
```

## Expected output

```text
Prompt chaining
===============
-- run 1: release with user-facing changes
[extract] v2.4 | - Dark mode across all screens | - CSV export for reports | - 40% faster search
[gate:extract] pass
[draft] Big news: version 2.4 is here! You asked, we listened: dark mode now covers every screen, you can export any report to CSV, and search is 40% faster. Update today and enjoy.
[compress] v2.4 is live: dark mode everywhere, CSV export for reports, and 40% faster search. Update now!
[gate:compress] pass
result: ok=True (94 chars)
-- run 2: internal-only release
[extract] NO_USER_FACING_CHANGES
[gate:extract] STOP — nothing user-facing to announce
result: ok=False stopped_at=extract
calls: run1=3, run2=1
```

Verified by `python3 code/verify.py prompt_chaining`.
