# Solution — 20. Context management

**Exercise.** Keep identifiers verbatim through lossy compaction.

**Approach.** Before turns are summarised, scan them for ticket-style ids and keep those in a pinned list. After the summarizer runs, append a `PINNED IDS:` line to the summary. The summarizer can paraphrase everything else.

```python
ID = re.compile(r"\b[A-Z]{2,6}-\d+\b")

class PinningContextManager(ContextManager):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pinned: list[str] = []

    def _compact(self, transcript):
        for turn in transcript[self.summarized_upto: max(0, len(transcript) - self.keep_recent)]:
            self.pinned += [i for i in ID.findall(turn) if i not in self.pinned]
        recent = super()._compact(transcript)
        if self.pinned and "PINNED IDS" not in self.summary:
            self.summary += f" PINNED IDS: {', '.join(self.pinned)}."
        return recent
```

Run: `python3 code/patterns/context_management/exercise_solution.py`

<!-- expected-output: code/patterns/context_management/exercise_solution.py -->
```text
Context management — exercise solution
======================================
[plain] CHG-881 in context=True, INC-4411 in context=False, tokens=177
[pinning] CHG-881 in context=True, INC-4411 in context=True, tokens=182
```

**Discussion.** Five extra tokens buy the guarantee. Note that `CHG-881` survived even without pinning, but only by luck: a recent turn repeated it. Extend the pattern to amounts, dates and names that later steps depend on. The general rule is to never let a summarizer be the only keeper of a fact that a decision depends on.
