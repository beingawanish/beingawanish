# Pattern 3 — Parallelization (fan-out/fan-in)

Run independent calls concurrently on a split known in advance; aggregate in code.

| | |
|---|---|
| Implementation | [`fanout.py`](fanout.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-1-workflow/03-parallelization.md`](../../../book/part-1-workflow/03-parallelization.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/parallelization/main.py
```

## Expected output

```text
Parallelization
===============
-- sectioning: three independent guardrail checks on a draft reply
[check:tone] pass=True — warm and professional
[check:policy] pass=False — promises a refund above the $50 agent limit
[check:facts] pass=True — order number and dates match the record
[fan-in] approved=False
[timing] parallel faster than sequential: True
-- voting: three judges on one email
[judge:A] PHISHING
[judge:B] PHISHING
[judge:C] discarded ("I'm not sure, it could be either.")
[fan-in] verdict=PHISHING agreement=1.00 from 2 usable votes
```

Verified by `python3 code/verify.py parallelization`.
