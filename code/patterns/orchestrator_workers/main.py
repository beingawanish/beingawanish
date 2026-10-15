"""Orchestrator-workers demo: the number and kind of subtasks is decided by the model.

Run:  python3 code/patterns/orchestrator_workers/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.orchestrator_workers.orchestrator import orchestrate  # noqa: E402

STORE = {
    "auth/login.py": "def login(u, p): ... # now rate-limited: 5 attempts / 15 min",
    "auth/session.py": "SESSION_TTL = 8 * 3600  # was 24h",
    "billing/invoice.py": "def render(inv): ... # unchanged",
    "docs/security.md": "## Sessions\nSessions expire after 8 hours.",
}

PR_PLAN = [
    {"id": "login", "instruction": "Summarise the behaviour change", "source": "auth/login.py"},
    {"id": "session", "instruction": "Summarise the behaviour change", "source": "auth/session.py"},
    {"id": "docs", "instruction": "Check the docs match the code", "source": "docs/security.md"},
]
NOTE_PLAN = [
    {"id": "session", "instruction": "Explain the user impact", "source": "auth/session.py"},
]
BAD_PLAN = [{"id": "x", "instruction": "Read the database", "source": "db/prod.sql"}]

orchestrator = MockLLM(rules([
    (lambda p, s: "TASK: Write the PR description" in p, json.dumps(PR_PLAN)),
    (lambda p, s: "TASK: Write a customer note" in p, json.dumps(NOTE_PLAN)),
    (lambda p, s: "TASK: Audit" in p, json.dumps(BAD_PLAN)),
    (lambda p, s: "SYNTHESIZE for task: Write the PR description" in p,
     "Security hardening: login is rate-limited (5 tries / 15 min) and sessions now last 8h "
     "instead of 24h. Docs updated and consistent."),
    (lambda p, s: "SYNTHESIZE for task: Write a customer note" in p,
     "Heads-up: for your security you'll now be asked to sign in again after 8 hours."),
]), name="large-orchestrator")

worker = MockLLM(rules([
    ("auth/login.py", "Adds rate limiting: 5 failed attempts per 15 minutes."),
    (lambda p, s: "user impact" in p, "Users are signed out after 8h instead of 24h."),
    ("auth/session.py", "Session lifetime reduced from 24h to 8h."),
    ("docs/security.md", "Docs say 8 hours — consistent with the code."),
]), name="small-worker", price=(0.25, 1.25))

TASKS = [
    "Write the PR description for the auth hardening change",
    "Write a customer note about the auth change",
    "Audit everything touching customer data",
]


def main() -> None:
    trace = Trace("Orchestrator-workers")
    results = []
    for task in TASKS:
        trace.note(f"-- {task}")
        results.append(orchestrate(orchestrator, worker, task, STORE, max_subtasks=4, trace=trace))
    trace.note(f"orchestrator: {orchestrator.usage.calls} calls; workers: {worker.usage.calls} calls")
    trace.print()

    assert [len(r.subtasks) for r in results] == [3, 1, 0]
    assert results[0].ok and results[1].ok and not results[2].ok
    assert worker.usage.calls == 4


if __name__ == "__main__":
    main()
