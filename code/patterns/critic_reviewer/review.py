"""Critic–reviewer loop: an author agent and a reviewer agent with *different tools*
iterate on an artefact through itemised findings until approval.

* The reviewer runs tools (tests, lint) and turns their output into findings with
  ids and severities. It never edits the artefact.
* The author answers every open finding — fixed, or won't-fix with a reason.
* Code tracks findings across rounds: a blocking finding cannot be waived by the
  author, only fixed; approval means no open blocking findings.

Reused by the coding-team capstone (QA team).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from agentkit import Trace


@dataclass
class Finding:
    id: str
    severity: str  # "blocking" | "nit"
    issue: str


@dataclass
class Response:
    finding_id: str
    action: str  # "fixed" | "wont_fix"
    note: str = ""


@dataclass
class ReviewRun:
    artefact: str
    approved: bool
    rounds: int
    open_findings: list[Finding] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


Author = Callable[[str, Optional[str], list[Finding]], tuple[str, list[Response]]]
Reviewer = Callable[[str], list[Finding]]


def review_loop(task: str, author: Author, reviewer: Reviewer, max_rounds: int = 3,
                trace: Optional[Trace] = None) -> ReviewRun:
    artefact, responses = author(task, None, [])
    waived: dict[str, str] = {}
    for rnd in range(1, max_rounds + 1):
        findings = [f for f in reviewer(artefact) if f.id not in waived]
        blocking = [f for f in findings if f.severity == "blocking"]
        if trace:
            trace.step(f"review {rnd}", "; ".join(f"{f.id}[{f.severity}] {f.issue}" for f in findings) or "no findings")
        if not blocking:
            return ReviewRun(artefact, True, rnd, findings)
        if rnd == max_rounds:
            break
        artefact, responses = author(task, artefact, findings)
        for r in responses:
            f = next((x for x in findings if x.id == r.finding_id), None)
            if f is None:
                continue
            if r.action == "wont_fix" and f.severity == "nit":
                waived[f.id] = r.note
            if trace:
                verdict = "accepted" if f.id in waived else ("noted" if r.action == "fixed" else "REJECTED (blocking)")
                trace.step(f"author {f.id}", f"{r.action}: {r.note} → {verdict}")
        unanswered = [f.id for f in findings if f.id not in {r.finding_id for r in responses}]
        if unanswered and trace:
            trace.step("author", f"did not answer {unanswered}; they stay open")
    return ReviewRun(artefact, False, max_rounds, [f for f in reviewer(artefact) if f.id not in waived])
