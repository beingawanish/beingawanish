"""Routing demo: five support tickets, four specialised handlers, one fallback.

Run:  python3 code/patterns/routing/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.routing.router import Router  # noqa: E402

ROUTES = {
    "billing": "charges, refunds, invoices, plans",
    "technical": "crashes, errors, bugs, performance",
    "account": "login, password, email, profile",
    "general": "anything else; human-friendly catch-all",
}
KEYWORDS = {
    "billing": ["charged", "refund", "invoice"],
    "technical": ["crash", "error", "bug"],
    "account": ["password", "email", "login"],
}

# The classifier model. Its behaviour per ticket is spelled out here.
classifier = MockLLM(rules([
    ("crashes on login", '{"route": "technical", "confidence": 0.86}'),
    ("student discount", '{"route": "billing", "confidence": 0.55}'),
    ("partnership", '{"route": "sales", "confidence": 0.9}'),
]), name="small-classifier", price=(0.25, 1.25))

# Specialists: each handler is its own prompt (and could be its own model).
specialist = MockLLM(rules([
    ("billing specialist", "I've refunded the duplicate charge; it will appear in 3-5 days."),
    ("technical specialist", "Please update to 3.2.1, which fixes the login crash."),
    ("account specialist", "You can change your email under Settings > Profile."),
    ("general support", "Thanks for reaching out! A teammate will follow up shortly."),
]), name="large-specialist")


def handler(role: str):
    return lambda text: specialist.complete(text, system=f"You are a {role}.")


HANDLERS = {
    "billing": handler("billing specialist"),
    "technical": handler("technical specialist"),
    "account": handler("account specialist"),
    "general": handler("general support agent"),
}

TICKETS = [
    "I was charged twice for March.",
    "The app crashes on login since yesterday.",
    "How do I update my email address?",
    "Do you offer a student discount?",
    "We'd like to discuss a partnership.",
]


def main() -> None:
    router = Router(classifier, ROUTES, fallback="general", threshold=0.7, keywords=KEYWORDS)
    trace = Trace("Routing")
    decisions = []
    for ticket in TICKETS:
        d, reply = router.dispatch(ticket, HANDLERS)
        decisions.append(d)
        why = f" ({d.reason})" if d.reason and d.method == "fallback" else ""
        trace.step(f"{d.route:<9}", f"via {d.method} conf={d.confidence:.2f}{why} :: {ticket}")
        trace.note(f"            -> {reply}")
    trace.note(f"classifier calls: {classifier.usage.calls} of {len(TICKETS)} tickets")
    trace.print()

    assert [d.route for d in decisions] == ["billing", "technical", "account", "general", "general"]
    assert classifier.usage.calls == 3  # keyword pre-filter answered two tickets for free


if __name__ == "__main__":
    main()
