# Solution — 18. Swarm

**Exercise.** Make claims expire so that work held by a crashed agent returns to the board.

**Approach.** Keep a logical clock (one tick per claim attempt) and the time each task was claimed. Before every claim, reopen tasks whose claim is older than the lease.

```python
class LeaseBoard(Blackboard):
    def __init__(self, lease: int = 1, **kw):
        super().__init__(**kw)
        self.lease, self.clock, self.claimed_at, self.expired = lease, 0, {}, []

    def claim(self, agent):
        self.clock += 1
        for t in self.tasks:  # reopen stale claims before looking for work
            if t.status == "claimed" and self.clock - self.claimed_at.get(t.id, self.clock) > self.lease:
                t.status, t.claimed_by = "open", None
                self.expired.append(t.id)
        task = super().claim(agent)
        if task:
            self.claimed_at[task.id] = self.clock
        return task
```

Run: `python3 code/patterns/swarm/exercise_solution.py`

<!-- expected-output: code/patterns/swarm/exercise_solution.py -->
```text
Swarm — exercise solution
=========================
[plain board] stalled: unfinished tasks, but no agent could make progress; done=2, unfinished=1
[lease board] board empty; done=3, unfinished=0, expired claims=['T1']
```

**Discussion.** The first version used a lease of 3, and the swarm stalled *before* the lease expired, because no agent made a claim attempt to advance the clock. A logical clock only moves when someone acts. Real systems use wall-clock leases plus a janitor process, which is a small piece of central control. That is the recurring lesson of the swarm chapter: the fixes for swarm failure modes reintroduce coordination.
