# Solution — 13. Hierarchical teams

**Exercise.** Contain a worker exception inside its team.

**Approach.** Wrap workers so that an exception becomes an error *result*. The team lead then sees `[error: …]` in its history and can decide what to do, here finishing with an unedited headline and saying so.

```python
def contained(worker):
    def run(instruction, state):
        try:
            return worker(instruction, state)
        except Exception as exc:
            return f"[error: {type(exc).__name__}: {exc}]"
    return run
```

Run: `python3 code/patterns/hierarchical_teams/exercise_solution.py`

<!-- expected-output: code/patterns/hierarchical_teams/exercise_solution.py -->
```text
Hierarchical teams — exercise solution
======================================
[launch_lead → content_team] Write the launch headline
[content_lead → writer] Draft
[writer] Draft: Scheduled exports are here — set it once, get your report every Monday.
[content_lead → editor] Tighten
[editor] [error: TimeoutError: style-guide service unavailable]
[content_lead] FINISH: Unedited headline (editor unavailable): 'Scheduled exports are here — set it once.'
[content_team] Unedited headline (editor unavailable): 'Scheduled exports are here — set it once.'
[launch_lead] FINISH: Launch copy ready (unedited).
result: ok=True; launch_lead saw: "Unedited headline (editor unavailable): 'Scheduled exports are here — set it once.'"
```

**Discussion.** The fault stopped at the team boundary and the parent got a *truthful* summary ("unedited, editor unavailable"). The containment belongs at the worker boundary, not in `Supervisor.run`, so each team decides its own failure semantics. A team whose lead cannot finish still returns `[team failed: …]` through `team_as_worker`.
