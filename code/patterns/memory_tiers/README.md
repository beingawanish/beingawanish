# Pattern 19 — Memory tiers

Working, episodic and semantic memory with a code-owned write policy and history.

| | |
|---|---|
| Implementation | [`memory.py`](memory.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-4-cross-cutting/19-memory-tiers.md`](../../../book/part-4-cross-cutting/19-memory-tiers.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/memory_tiers/main.py
```

## Expected output

```text
Memory tiers
============
-- session s1
[s1 write] name=Ana -> semantic (added)
[s1 write] diet=vegetarian -> semantic (added)
[s1 write] allergy=peanuts -> semantic (added)
[s1 write] location_this_week=Porto -> episodic (transient)
[s1 write] cuisine=Thai -> dropped (confidence 0.45 < 0.7)
[s1 working] last 2 turns only: This week I'm in Porto… | I think I might like T…
-- session s2 (new process): 'Suggest a dinner recipe'
[s2 recall] allergy=peanuts, diet=vegetarian
[s2 episodic] search 'Porto' -> ['location_this_week=Porto']
[s2 write] diet=pescatarian -> semantic (updated)
-- session s3 (new process)
[s3 recall] diet=pescatarian (history: ['vegetarian'], source: 'Actually, I eat fish now.')
[s3 store] 3 semantic facts, 1 episodic notes
```

> **Reused, not copied:** the deep-research capstone imports this module.

Verified by `python3 code/verify.py memory_tiers`.
