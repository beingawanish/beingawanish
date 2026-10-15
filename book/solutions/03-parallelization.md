# Solution — 3. Parallelization

**Exercise.** Require a quorum of three usable votes, and report agreement against votes *cast*.

**Approach.** Keep `majority_vote` and wrap it with the two rules:

```python
def vote_with_quorum(votes, cast: int, quorum: int):
    if len(votes) < quorum:
        return None, f"no quorum ({len(votes)}/{cast} usable, need {quorum})"
    winner, _ = majority_vote(votes)
    agreement = votes.count(winner) / cast if winner else 0.0
    return winner, f"agreement {agreement:.2f} of {cast} cast"
```

Run: `python3 code/patterns/parallelization/exercise_solution.py`

<!-- expected-output: code/patterns/parallelization/exercise_solution.py -->
```text
Parallelization — exercise solution
===================================
[2 usable of 3] verdict=None — no quorum (2/3 usable, need 3)
[3 usable of 3] verdict=PHISHING — agreement 0.67 of 3 cast
```

**Discussion.** With two usable votes out of three, the honest answer is "no verdict". Escalate, or cast one more vote with a *different* prompt or model, which also decorrelates the voters. Reporting agreement against votes cast (0.67, not 1.00) keeps downstream thresholds meaningful: a policy of "auto-act above 0.9 agreement" would otherwise fire on two votes.
