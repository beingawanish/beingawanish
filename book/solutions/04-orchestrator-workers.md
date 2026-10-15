# Solution — 4. Orchestrator–workers

**Exercise.** Retry transient worker failures once, without changing `orchestrate()`.

**Approach.** Every pattern depends only on the `complete(prompt, system)` protocol. A *decorator* that implements the same protocol can add retries around any model, and the orchestrator never knows:

```python
class RetryingLLM:
    def __init__(self, inner, attempts: int = 2, retry_on=(TimeoutError, ConnectionError)):
        self.inner, self.attempts, self.retry_on = inner, attempts, retry_on
        self.retries = 0

    def complete(self, prompt, system=""):
        for i in range(self.attempts):
            try:
                return self.inner.complete(prompt, system)
            except self.retry_on:
                if i == self.attempts - 1:
                    raise
                self.retries += 1
```

Run: `python3 code/patterns/orchestrator_workers/exercise_solution.py`

<!-- expected-output: code/patterns/orchestrator_workers/exercise_solution.py -->
```text
Orchestrator-workers — exercise solution
========================================
-- without retry
[plan] 3 subtask(s): login, session, docs
[worker:login] Adds rate limiting: 5 failed attempts per 15 minutes.
[worker:session] [worker failed: TimeoutError: worker call timed out]
[worker:docs] Docs say 8 hours — consistent with the code.
[synthesize] Security hardening: login is rate-limited (5 tries / 15 min) and sessions now last 8h instead of 24h. Docs updated and consistent.
-- with RetryingLLM
[plan] 3 subtask(s): login, session, docs
[worker:login] Adds rate limiting: 5 failed attempts per 15 minutes.
[worker:session] Session lifetime reduced from 24h to 8h.
[worker:docs] Docs say 8 hours — consistent with the code.
[synthesize] Security hardening: login is rate-limited (5 tries / 15 min) and sessions now last 8h instead of 24h. Docs updated and consistent.
retries used: 1
```

**Discussion.** Retry only *transient* errors (timeouts, connection resets, rate limits). A worker that returns nonsense will return nonsense again, so retrying it just doubles cost. Notice also that in the "without retry" run the mock synthesis did not mention the missing session result. A real synthesis prompt should be told to report failed subtasks, and the [eval harness](../part-4-cross-cutting/21-eval-harness.md) should include a case with a forced worker failure to check that it does.
