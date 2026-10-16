"""Exercise solution — Orchestrator-workers.

Task: one worker call fails transiently (a timeout). Today the synthesis receives
"[worker failed: ...]". Make workers retry once on failure *without changing
orchestrate()* — then show the synthesis gets all three results.

Run:  python3 code/patterns/orchestrator_workers/exercise_solution.py
"""

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.orchestrator_workers.main import STORE, TASKS, orchestrator, worker  # noqa: E402
from patterns.orchestrator_workers.orchestrator import orchestrate  # noqa: E402


class FlakyLLM:
    """Fails the first call that mentions `trigger`, then behaves."""

    def __init__(self, inner, trigger):
        self.inner, self.trigger, self.tripped = inner, trigger, False
        self._lock = threading.Lock()

    def complete(self, prompt, system=""):
        with self._lock:
            trip = self.trigger in prompt and not self.tripped
            self.tripped = self.tripped or trip
        if trip:
            raise TimeoutError("worker call timed out")
        return self.inner.complete(prompt, system)


class RetryingLLM:
    """The solution: a decorator around any LLM. Same protocol, so orchestrate() is untouched."""

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


def main() -> None:
    trace = Trace("Orchestrator-workers — exercise solution")
    trace.note("-- without retry")
    orchestrate(orchestrator, FlakyLLM(worker, "auth/session.py"), TASKS[0], STORE, trace=trace)
    trace.note("-- with RetryingLLM")
    robust = RetryingLLM(FlakyLLM(worker, "auth/session.py"))
    result = orchestrate(orchestrator, robust, TASKS[0], STORE, trace=trace)
    trace.note(f"retries used: {robust.retries}")
    trace.print()
    assert not any(v.startswith("[worker failed") for v in result.worker_outputs.values())
    assert robust.retries == 1


if __name__ == "__main__":
    main()
