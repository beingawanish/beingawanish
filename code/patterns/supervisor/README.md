# Pattern 12 — Supervisor

One coordinator repeatedly picks the next specialist agent and decides when the job is done.

| | |
|---|---|
| Implementation | [`supervisor.py`](supervisor.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-3-multi-agent/12-supervisor.md`](../../../book/part-3-multi-agent/12-supervisor.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/supervisor/main.py
```

## Expected output

```text
Supervisor
==========
-- Write a one-sentence pricing brief
[supervisor → researcher] Collect competitor list prices
[researcher] Monthly list prices: Acme (us) $49, Beta $59, Gamma $45
[supervisor → writer] Draft one sentence positioning our price
[writer] Acme sits between Beta and Gamma on price.
[supervisor → analyst] Compute our price difference vs each competitor in %
[analyst] Acme vs competitors: -17% vs Beta, +9% vs Gamma
[supervisor → writer] Redraft using the percentage comparison
[writer] Acme is priced mid-market: 17% below Beta and 9% above Gamma.
[supervisor] FINISH: Acme is priced mid-market: 17% below Beta and 9% above Gamma.
result: finished after 4 worker turns, 5 supervisor calls
-- Same task, a supervisor that repeats itself
[supervisor → researcher] Collect competitor list prices
[researcher] Monthly list prices: Acme (us) $49, Beta $59, Gamma $45
[supervisor] STOP — loop: researcher already did 'Collect competitor list prices'
result: ok=False, loop: researcher already did 'Collect competitor list prices'
```

> **Reused, not copied:** the coding-team capstone imports this module.

Verified by `python3 code/verify.py supervisor`.
