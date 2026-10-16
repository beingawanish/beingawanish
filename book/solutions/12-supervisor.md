# Solution — 12. Supervisor

**Exercise.** Cut supervisor prompt growth without changing `Supervisor.run()`.

**Approach.** Subclass and override only `_decide`. Give the supervisor a clipped copy of the history; workers still keep full results in shared state.

```python
class BriefingSupervisor(Supervisor):
    def __init__(self, *a, max_chars: int = 80, **kw):
        super().__init__(*a, **kw)
        self.max_chars = max_chars

    def _decide(self, task, run):
        clipped = SupervisorRun(run.ok, run.final,
                                [(w, i, o if len(o) <= self.max_chars else o[: self.max_chars] + "…")
                                 for w, i, o in run.turns])
        return super()._decide(task, clipped)
```

Run: `python3 code/patterns/supervisor/exercise_solution.py`

<!-- expected-output: code/patterns/supervisor/exercise_solution.py -->
```text
Supervisor — exercise solution
==============================
[full history] ok=True turns=4 supervisor prompt tokens=1446
[clipped history] ok=True turns=4 supervisor prompt tokens=523
```

**Discussion.** Same decisions, about a third of the prompt tokens. It works because the supervisor only needs to know *what happened*, not the full content; the analyst read prices from `state`. Clipping by character count is the bluntest tool. Better is to have each worker return a one-line status plus an artefact id, which is the summary contract from [hierarchical teams](../part-3-multi-agent/13-hierarchical-teams.md).
