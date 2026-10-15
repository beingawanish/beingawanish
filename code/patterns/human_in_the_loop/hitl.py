"""Human-in-the-loop: pause risky actions at a checkpoint, persist state, resume exactly once.

Canonical module: the support-triage capstone imports this file.

Design rules encoded here:
* The *policy* (code) decides what needs review; the model never decides its own oversight.
* The review queue is durable (a JSON file), so a paused workflow survives restarts.
* Resuming is idempotent: an approved action executes at most once.
* Silence is not consent: undecided requests expire to "rejected" after their deadline.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Action:
    kind: str
    payload: dict[str, Any]
    confidence: float = 1.0


# A policy rule returns a reason string if the action needs a human, else None.
Rule = Callable[[Action], Optional[str]]


@dataclass
class Policy:
    rules: list[Rule] = field(default_factory=list)

    def reasons(self, action: Action) -> list[str]:
        return [r for rule in self.rules if (r := rule(action))]


@dataclass
class Outcome:
    status: str  # executed | pending | rejected | expired | already-executed | needs-reconcile
    request_id: Optional[str] = None
    result: Any = None
    detail: str = ""


class ReviewQueue:
    """File-backed review queue. Every mutation is written to disk immediately."""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        self._data = json.loads(self.path.read_text()) if self.path.exists() else {"seq": 0, "requests": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        tmp.replace(self.path)  # atomic on POSIX: never a half-written queue

    def submit(self, action: Action, reasons: list[str], context: dict, now: int, ttl: int) -> str:
        self._data["seq"] += 1
        rid = f"R{self._data['seq']:03d}"
        self._data["requests"][rid] = {
            "action": asdict(action), "reasons": reasons, "context": context,
            "status": "pending", "decision": None, "deadline": now + ttl,
        }
        self._save()
        return rid

    def get(self, rid: str) -> dict:
        return self._data["requests"][rid]

    def pending(self) -> list[str]:
        return [rid for rid, r in self._data["requests"].items() if r["status"] == "pending"]

    def decide(self, rid: str, verdict: str, reviewer: str, edits: Optional[dict] = None, note: str = "") -> None:
        if verdict not in ("approve", "edit", "reject"):
            raise ValueError(f"unknown verdict {verdict!r}")
        req = self.get(rid)
        if req["status"] != "pending":
            raise ValueError(f"{rid} is {req['status']}, not pending")
        req["decision"] = {"verdict": verdict, "reviewer": reviewer, "edits": edits or {}, "note": note}
        req["status"] = "rejected" if verdict == "reject" else "approved"
        self._save()

    def expire(self, now: int) -> list[str]:
        expired = [rid for rid in self.pending() if self.get(rid)["deadline"] <= now]
        for rid in expired:
            self.get(rid)["status"] = "expired"
        if expired:
            self._save()
        return expired

    def mark_executing(self, rid: str) -> None:
        self.get(rid)["status"] = "executing"
        self._save()

    def mark_executed(self, rid: str, result: Any) -> None:
        req = self.get(rid)
        req["status"], req["result"] = "executed", result
        self._save()


Executor = Callable[[Action], Any]


def submit_or_execute(action: Action, policy: Policy, queue: ReviewQueue, execute: Executor,
                      context: dict, now: int, ttl: int = 24) -> Outcome:
    reasons = policy.reasons(action)
    if not reasons:
        return Outcome("executed", result=execute(action), detail="auto: no policy rule fired")
    rid = queue.submit(action, reasons, context, now, ttl)
    return Outcome("pending", rid, detail="; ".join(reasons))


def resume(queue: ReviewQueue, rid: str, execute: Executor) -> Outcome:
    req = queue.get(rid)
    status = req["status"]
    if status == "executed":
        return Outcome("already-executed", rid, req.get("result"), "idempotent: not re-run")
    if status == "executing":
        # We crashed between starting the side effect and recording it. Re-running could
        # double-refund; a human (or the executor's idempotency key) must reconcile.
        return Outcome("needs-reconcile", rid, detail="side effect may or may not have happened")
    if status in ("rejected", "expired", "pending"):
        note = (req.get("decision") or {}).get("note", "")
        return Outcome(status, rid, detail=note or ("awaiting reviewer" if status == "pending" else "default deny"))
    payload = {**req["action"]["payload"], **req["decision"]["edits"]}
    action = Action(req["action"]["kind"], payload, req["action"]["confidence"])
    queue.mark_executing(rid)          # write-ahead: record intent before the side effect
    result = execute(action)
    queue.mark_executed(rid, result)
    return Outcome("executed", rid, result, f"{req['decision']['verdict']} by {req['decision']['reviewer']}")
