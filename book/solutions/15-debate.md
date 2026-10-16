# Solution — 15. Debate

**Exercise.** Detect a judge whose verdict depends on speaking order.

**Approach.** Run the same debate twice with the debaters' order reversed. An argument-weighing judge decides the same way both times; a biased one flips.

```python
def order_robust(judge_llm, debaters, question):
    a = debate(debaters, judge_llm, question)
    b = debate(list(reversed(debaters)), judge_llm, question)
    return a.decision == b.decision, a.decision, b.decision
```

Run: `python3 code/patterns/debate/exercise_solution.py`

<!-- expected-output: code/patterns/debate/exercise_solution.py -->
```text
Debate — exercise solution
==========================
[argument-based judge] order-stable=True
[recency-biased judge] order-stable=False ('Do not split yet' vs 'Split now') → escalate
```

**Discussion.** The check doubles the cost of a debate, so reserve it for decisions that matter, or run it on a sample to certify a judge model. The same trick catches position bias in [LLM-judge scorers](../part-4-cross-cutting/21-eval-harness.md) when comparing two candidate outputs: score A-then-B and B-then-A.
