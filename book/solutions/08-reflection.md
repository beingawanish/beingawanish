# Solution — 8. Reflection

**Exercise.** Learn a lesson from an externally revealed failure and carry it into the next task.

**Approach.** Lessons are a list of strings, passed as system text to `reflect()`. After a task, an outside signal (here, tests) decides whether a lesson is needed, and the model writes it.

```python
before = reflect(model, task)
if not passes(before.output):  # an outside signal reveals the failure
    lessons.append(model.complete(f"LESSON from failure on: {task}"))
after = reflect(model, task, system="\n".join(lessons))
```

Run: `python3 code/patterns/reflection/exercise_solution.py`

<!-- expected-output: code/patterns/reflection/exercise_solution.py -->
```text
Reflection — exercise solution
==============================
[without lessons] tests pass=False
[stored] Lesson: month-length code must handle February in leap years.
[with lessons] tests pass=True
```

**Discussion.** The lesson works because it carries information the model's self-critique lacked: *that it fails at leap-year Februaries*. Reflection alone could not produce that; the test result did. This is the Reflexion insight: self-improvement needs an external signal, and memory carries it forward. In production, store lessons in [memory (#19)](../part-4-cross-cutting/19-memory-tiers.md) with the failure that produced them, cap how many are injected, and retire lessons that stop correlating with better outcomes.
