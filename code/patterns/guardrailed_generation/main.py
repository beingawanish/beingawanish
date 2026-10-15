"""Guardrailed generation demo: a support reply that is repaired twice, and one that falls back.

Run:  python3 code/patterns/guardrailed_generation/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.guardrailed_generation.guardrails import (  # noqa: E402
    CARD_NUMBER, forbid_pattern, guarded_generate, max_value, max_words, require_fields,
)

VALIDATORS = [
    require_fields(reply=str, refund=(int, float), tags=list),
    forbid_pattern("reply", CARD_NUMBER, "reply must not contain a card number"),
    max_value("refund", 50.0, "refund {value} exceeds the agent limit of {limit}"),
    max_words("reply", 40),
]
FALLBACK = {"reply": "Thanks for your patience — a teammate will review your case today.",
            "refund": 0.0, "tags": ["needs-human"]}

PROMPT = "Draft a JSON support reply with keys reply, refund, tags for ticket: {ticket}"

model = MockLLM(rules([
    # Ticket 1 — repaired twice.
    (lambda p, s: "#4471" in p and "card number" in p,
     '{"reply": "Refunded $45 to your card. Sorry for the trouble!", "refund": 45.0, "tags": ["refund"]}'),
    (lambda p, s: "#4471" in p and "REPAIR" in p,
     '{"reply": "Refunded $45 to card 4111 1111 1111 1111.", "refund": 45.0, "tags": ["refund"]}'),
    (lambda p, s: "#4471" in p,
     "Sure! Here's a reply: we've refunded you $45."),
    # Ticket 2 — the model keeps over-refunding; repairs don't converge.
    (lambda p, s: "#5120" in p,
     '{"reply": "Full refund of $180 issued.", "refund": 180.0, "tags": ["refund"]}'),
]))


def main() -> None:
    trace = Trace("Guardrailed generation")
    trace.note("-- ticket #4471: double charge of $45")
    r1 = guarded_generate(model, PROMPT.format(ticket="#4471 double charge of $45"), VALIDATORS,
                          fallback=FALLBACK, trace=trace)
    trace.note(f"result: ok={r1.ok} attempts={r1.attempts} reply={r1.value['reply']!r}")
    trace.note("-- ticket #5120: wants a full $180 refund")
    r2 = guarded_generate(model, PROMPT.format(ticket="#5120 wants a full $180 refund"), VALIDATORS,
                          fallback=FALLBACK, trace=trace)
    trace.note(f"result: ok={r2.ok} attempts={r2.attempts} used_fallback={r2.used_fallback} "
               f"tags={r2.value['tags']}")
    trace.print()

    assert r1.ok and r1.attempts == 3
    assert not r2.ok and r2.used_fallback and r2.value == FALLBACK


if __name__ == "__main__":
    main()
