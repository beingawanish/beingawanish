# Solution — 5. Evaluator–optimizer

**Exercise.** Reject over-long drafts with a free code check before the evaluator runs. Do not modify `optimize()`.

**Approach.** Wrap the evaluator in an object with the same `complete()` protocol. It answers deterministically when the cheap check fails, and delegates otherwise:

```python
class PrecheckedEvaluator:
    def __init__(self, inner, max_words: int):
        self.inner, self.max_words, self.short_circuits = inner, max_words, 0

    def complete(self, prompt, system=""):
        draft = prompt.split("Draft:\n", 1)[1].split("\n\nReply", 1)[0]
        words = len(draft.split())
        if words >= self.max_words:
            self.short_circuits += 1
            return json.dumps({"pass": False, "feedback": [f"Cut to under {self.max_words} words (now {words})"]})
        return self.inner.complete(prompt, system)
```

Run: `python3 code/patterns/evaluator_optimizer/exercise_solution.py`

<!-- expected-output: code/patterns/evaluator_optimizer/exercise_solution.py -->
```text
Evaluator-optimizer — exercise solution
=======================================
[round 1 draft] Hi Sam, I am so incredibly sorry to hear that your order #4471 arrived six whole days later than we promised. I completely understand how frustrating it must have been to wait, especially after you had planned around the original delivery date. That's on us, and we take it seriously. I've refunded your $9.99 shipping fee today, and our whole team is reviewing what went wrong so it never happens again.
[round 1 eval] FAIL: Cut to under 60 words (now 71)
[round 2 draft] Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. I've refunded your $9.99 shipping fee today.
[round 2 eval] PASS
passed=True rounds=2; evaluator calls=1, saved by pre-check=1
```

**Discussion.** One evaluator call saved out of two. On real traffic the saving is the share of drafts failing *any* mechanical criterion. The feedback is also *better* than a model's: an exact count ("now 71") instead of "too long". Parsing the draft back out of the prompt is a shortcut that suits an exercise. In production, give the optimizer an explicit `precheck(draft)` hook. This is a small step toward [guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md): code checks first, model judgement only for what code cannot decide.
