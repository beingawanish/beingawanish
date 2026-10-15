# Pattern 18 — Swarm

Peer agents coordinate through a shared blackboard with no central controller.

| | |
|---|---|
| Implementation | [`swarm.py`](swarm.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-3-multi-agent/18-swarm.md`](../../../book/part-3-multi-agent/18-swarm.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/swarm/main.py
```

## Expected output

```text
Swarm
=====
-- bug-report swarm (no controller; agents claim by skill)
[t1 triager] T1 report: bug → posted ['T5']
[t1 reproducer] T5 repro: could not reproduce on Safari 18; asked reporter for version
[t2 triager] T2 report: feature request → product backlog
[t3 triager] T3 report: bug
[t4 triager] T4 report: bug → posted ['T6']
[t4 reproducer] T6 repro: reproduced: rounding applied before VAT → posted ['T7']
[t4 estimator] T7 estimate: small: 1 day
result: board empty after 4 ticks; 7 model calls for 4 reports; duplicate repro tasks suppressed by the board
-- runaway swarm: an agent that posts 2 follow-ups per task
result: tick budget 4 spent; 8 calls; tasks=12 (cap 12), unfinished=4, posts rejected by cap=5
```

Verified by `python3 code/verify.py swarm`.
