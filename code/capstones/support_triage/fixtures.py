"""Fixtures for the support-triage capstone: mock CRM, mock KB, the eval set, and the
mock model's behaviour. Everything that would be "the outside world" lives here."""

from __future__ import annotations

import json

from agentkit import MockLLM, ToolError, ToolRegistry, rules
from patterns.eval_harness.harness import Case

CRM = {
    "c1": {"tier": "standard", "order_total": 58},
    "c2": {"tier": "standard", "order_total": 0},
    "c3": {"tier": "vip", "order_total": 240},
    "c4": {"tier": "standard", "order_total": 99},
    # c5 is deliberately missing: the CRM lookup fails and triage must carry on (R1).
    "c6": {"tier": "standard", "order_total": 60},
    "c7": {"tier": "vip", "order_total": 300},
    "c8": {"tier": "standard", "order_total": 30},
}
KB = {
    "charge": "Duplicate charges and refunds",
    "crash": "Fixing crashes after an update",
    "export": "Exporting your data",
    "email": "Changing your email address",
    "invoice": "Downloading invoices",
}


def make_tools() -> ToolRegistry:
    tools = ToolRegistry()

    @tools.register("crm_lookup", "Customer tier and order total", customer_id=str)
    def crm_lookup(customer_id: str) -> dict:
        if customer_id not in CRM:
            raise ToolError(f"customer {customer_id} not found")
        return CRM[customer_id]

    @tools.register("kb_search", "Best help-centre article for a query", query=str)
    def kb_search(query: str) -> str:
        low = query.lower()
        return next((title for key, title in KB.items() if key in low), "(no article)")

    return tools


# --- The eval set (R5). Expected values were written from the brief, before the solution.
TICKETS = [
    {"id": "TK-101", "customer_id": "c1", "text": "I was charged twice for order A100."},
    {"id": "TK-102", "customer_id": "c2", "text": "The app crashes on login since the update."},
    {"id": "TK-103", "customer_id": "c3",
     "text": "Third time you've overcharged me!!! Refund the $240 NOW or I'm leaving."},
    {"id": "TK-104", "customer_id": "c4", "text": "How do I export my data?"},
    {"id": "TK-105", "customer_id": "c5", "text": "Please update my email to sam@new.example."},
    {"id": "TK-106", "customer_id": "c6", "text": "I want a refund for order A600, it never arrived."},
    {"id": "TK-107", "customer_id": "c7", "text": "Error when downloading my invoice."},
    {"id": "TK-108", "customer_id": "c8", "text": "Card 4111 1111 1111 1111 was charged twice ($15)."},
]
EXPECTED = {
    "TK-101": {"route": "billing", "status": "sent"},
    "TK-102": {"route": "technical", "status": "sent"},
    "TK-103": {"route": "billing", "status": "pending"},
    "TK-104": {"route": "account", "status": "pending"},  # truth is account; system will fall back
    "TK-105": {"route": "account", "status": "sent"},
    "TK-106": {"route": "billing", "status": "pending"},
    "TK-107": {"route": "technical", "status": "sent"},
    "TK-108": {"route": "billing", "status": "sent"},
}
CRITICAL = {"TK-103", "TK-106", "TK-108"}  # money or PII at stake

CASES = [Case(t["id"], t, EXPECTED[t["id"]], ("critical",) if t["id"] in CRITICAL else ()) for t in TICKETS]


# --- Mock model behaviour --------------------------------------------------------------

def _j(reply: str, refund: float) -> str:
    return json.dumps({"reply": reply, "refund": refund})


def _draft(tid: str, repair: bool = False):
    return lambda p, s: f"DRAFT reply for ticket {tid}" in p and (("REPAIR" in p) == repair)


def _judge(prompt: str, system: str) -> str:
    generic = "a specialist will review your case" in prompt
    return '{"score": %s}' % ("0.6" if generic else "0.9")


def make_llm() -> MockLLM:
    return MockLLM(rules([
        (lambda p, s: p.startswith("SENTIMENT of ticket TK-103"), "angry"),
        (lambda p, s: p.startswith("SENTIMENT"), "neutral"),
        # Router classifier (only reached when keywords are ambiguous or absent).
        (lambda p, s: "classifier" in s and "crashes on login" in p, '{"route": "technical", "confidence": 0.86}'),
        (lambda p, s: "classifier" in s and "export my data" in p, '{"route": "account", "confidence": 0.62}'),
        (lambda p, s: "classifier" in s and "downloading my invoice" in p, '{"route": "technical", "confidence": 0.81}'),
        # Drafts.
        (_draft("TK-101"), _j("Sorry about the double charge on order A100. I've refunded the duplicate $29; "
                              "it will appear in 3-5 days.", 29)),
        (_draft("TK-102"), _j("Sorry about the crash. Version 3.2.1 fixes the login crash; please update from "
                              "the app store and reply here if it persists.", 0)),
        (_draft("TK-103"), _j("I'm truly sorry for the repeated overcharges. I've arranged a full $240 refund "
                              "and flagged your account so this cannot happen again.", 240)),
        (_draft("TK-104"), _j("You can export your data from Settings > Privacy > Export. The file arrives by "
                              "email within an hour.", 0)),
        (_draft("TK-105", repair=True), _j("Done! Your email is now sam@new.example. You'll get a confirmation "
                                           "link at the new address.", 0)),
        (_draft("TK-105"), "Sure, I've updated the email for you."),                 # prose, not JSON
        (_draft("TK-106", repair=True), _j("Full refund of $900 issued for order A600.", 900)),
        (_draft("TK-106"), _j("Full refund of $900 issued for order A600.", 900)),  # never converges
        (_draft("TK-107"), _j("Sorry about that error. We fixed the invoice download bug in today's release; "
                              "please refresh and try again.", 0)),
        (_draft("TK-108", repair=True), _j("Sorry for the double charge. I've refunded the duplicate $15 to "
                                           "your card ending 1111.", 15)),
        (_draft("TK-108"), _j("Refunded $15 to card 4111 1111 1111 1111.", 15)),   # echoes the PAN
    ]))


def make_judge() -> MockLLM:
    """A separate judge model: never grade a system with the model that produced its output."""
    return MockLLM(_judge, name="judge")
