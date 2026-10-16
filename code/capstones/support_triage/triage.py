"""Support triage: the glue. Every pattern used here is imported, not re-implemented."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from agentkit import LLM, ToolRegistry, Trace
from patterns.guardrailed_generation.guardrails import (
    CARD_NUMBER, forbid_pattern, guarded_generate, max_words, require_fields,
)
from patterns.human_in_the_loop.hitl import Action, Policy, ReviewQueue, submit_or_execute
from patterns.parallelization.fanout import fan_out
from patterns.routing.router import Router

ROUTES = {
    "billing": "charges, refunds, invoices",
    "technical": "crashes, errors, bugs",
    "account": "login, password, email, profile",
    "general": "anything else",
}
KEYWORDS = {
    "billing": ["charged", "refund", "invoice"],
    "technical": ["crash", "error", "bug"],
    "account": ["password", "email", "login"],
}
SAFE_HOLDING_REPLY = {"reply": "Thanks for your patience — a specialist will review your case today.",
                      "refund": 0}


@dataclass
class TriageOutcome:
    ticket_id: str
    route: str
    sentiment: str
    reply: str
    refund: float
    status: str  # "sent" | "pending"
    reasons: list[str] = field(default_factory=list)
    request_id: Optional[str] = None


def refund_within_order(order_total: float):
    def check(v: Any) -> list[str]:
        r = v.get("refund", 0) if isinstance(v, dict) else 0
        return [f"refund {r} exceeds order total {order_total}"] if isinstance(r, (int, float)) and r > order_total else []
    return check


def escalation_policy(route_method: str, used_fallback: bool, tier: str, sentiment: str) -> Policy:
    """R4. Built per ticket because some rules depend on context, not just the action."""
    return Policy([
        lambda a: f"refund ${a.payload['refund']} > $50" if a.payload["refund"] > 50 else None,
        lambda a: "VIP customer is angry" if tier == "vip" and sentiment == "angry" else None,
        lambda a: "route fell back to general" if route_method == "fallback" else None,
        lambda a: "guardrail fallback used" if used_fallback else None,
    ])


class TriageSystem:
    def __init__(self, llm: LLM, tools: ToolRegistry, queue: ReviewQueue, outbox: list) -> None:
        self.llm, self.tools, self.queue, self.outbox = llm, tools, queue, outbox
        self.router = Router(llm, ROUTES, fallback="general", threshold=0.7, keywords=KEYWORDS)

    def _send(self, action: Action) -> str:
        self.outbox.append((action.payload["ticket_id"], action.payload["reply"]))
        return "sent"

    def handle(self, ticket: dict, now: int = 0, trace: Optional[Trace] = None) -> TriageOutcome:
        tid, text = ticket["id"], ticket["text"]

        # R1 — parallel enrichment; each branch fails independently.
        branches = {b.name: b for b in fan_out({
            "customer": lambda: self.tools.call("crm_lookup", {"customer_id": ticket["customer_id"]}),
            "sentiment": lambda: self.llm.complete(f"SENTIMENT of ticket {tid}: {text}").strip().lower(),
            "kb": lambda: self.tools.call("kb_search", {"query": text}),
        })}
        customer = branches["customer"].value if branches["customer"].ok else {"tier": "unknown", "order_total": 0}
        sentiment = branches["sentiment"].value if branches["sentiment"].ok else "unknown"
        kb = branches["kb"].value if branches["kb"].ok else "(no article)"
        if trace:
            trace.step("enrich", f"customer={customer} sentiment={sentiment} kb={kb!r}")

        # R2 — routing.
        decision = self.router.classify(text)
        if trace:
            trace.step("route", f"{decision.route} via {decision.method} ({decision.confidence:.2f}) {decision.reason}".rstrip())

        # R3 — guardrailed draft.
        prompt = (f"DRAFT reply for ticket {tid} as JSON with keys reply, refund.\nRoute: {decision.route}\n"
                  f"Customer tier: {customer['tier']}\nHelp article: {kb}\nTicket: {text}")
        guard = guarded_generate(
            self.llm, prompt,
            [require_fields(reply=str, refund=(int, float)),
             forbid_pattern("reply", CARD_NUMBER, "reply must not contain a card number"),
             max_words("reply", 60),
             refund_within_order(customer["order_total"])],
            max_repairs=2, fallback=SAFE_HOLDING_REPLY, trace=trace,
        )
        draft = guard.value

        # R4 — human-in-the-loop checkpoint.
        policy = escalation_policy(decision.method, guard.used_fallback, customer["tier"], sentiment)
        action = Action("send_reply", {"ticket_id": tid, "reply": draft["reply"], "refund": draft["refund"]})
        out = submit_or_execute(action, policy, self.queue, self._send, context={"ticket": ticket}, now=now)
        status = "sent" if out.status == "executed" else "pending"
        reasons = policy.reasons(action)
        if trace:
            trace.step("decide", " ".join(x for x in (status, out.request_id, "; ".join(reasons)) if x))

        return TriageOutcome(tid, decision.route, sentiment, draft["reply"], draft["refund"],
                             status, reasons, out.request_id)
