# Pattern 16 — Critic–reviewer loop

An author agent and a tool-using reviewer agent iterate on itemised findings until approval.

| | |
|---|---|
| Implementation | [`review.py`](review.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-3-multi-agent/16-critic-reviewer.md`](../../../book/part-3-multi-agent/16-critic-reviewer.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/critic_reviewer/main.py
```

## Expected output

```text
Critic–reviewer loop
====================
[review 1] F1[blocking] accents are not transliterated; F2[blocking] separators wrong: want single dashes between words, none at ends; F3[nit] add a docstring
[author F1] fixed: NFKD + ASCII fold → noted
[author F2] fixed: collapse non-alnum runs, strip dashes → noted
[author F3] wont_fix: one-line helper; the name is the doc → accepted
[review 2] no findings
result: approved=True in 2 rounds; remaining findings: none; tests failing now: 0
calls: author=2, reviewer=2
```

> **Reused, not copied:** the coding-team capstone imports this module.

Verified by `python3 code/verify.py critic_reviewer`.
