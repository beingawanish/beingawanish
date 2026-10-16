"""Exercise solution — Sequential handoffs.

Task: the technical agent tries to hand off to "refunds", an agent that does not
exist, and the runtime escalates the whole conversation to a human. Give the agent
one chance to correct an invalid target (tell it the allowed targets) before the
runtime's escalation applies. Do not modify HandoffRuntime.

Run:  python3 code/patterns/sequential_handoffs/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, extract_json  # noqa: E402
from patterns.sequential_handoffs.handoff import Agent, HandoffRuntime  # noqa: E402
from patterns.sequential_handoffs.main import AGENTS  # noqa: E402


class GraphAwareLLM:
    """Wraps an agent's model: an invalid handoff target gets one corrective re-ask."""

    def __init__(self, inner, allowed: frozenset[str]):
        self.inner, self.allowed, self.corrections = inner, allowed, 0

    def complete(self, prompt, system=""):
        raw = self.inner.complete(prompt, system)
        target = extract_json(raw).get("handoff_to")
        if target is None or target in self.allowed:
            return raw
        self.corrections += 1
        return self.inner.complete(f"{prompt}\nCORRECTION: '{target}' does not exist. "
                                   f"Valid targets: {sorted(self.allowed)}.", system)


def confused_technical(prompt, system):
    if "CORRECTION" in prompt:
        return json.dumps({"handoff_to": "billing", "reason": "refund request", "summary": "Wants refund for outage."})
    return json.dumps({"handoff_to": "refunds", "reason": "refund request", "summary": "Wants refund for outage."})


SLA_BILLING = Agent("billing", MockLLM(lambda p, s: json.dumps(
    {"reply": "Per our SLA I've applied a one-day service credit to your next invoice."})), "Charges.", frozenset())


def main() -> None:
    trace = Trace("Sequential handoffs — exercise solution")
    for label, wrap in (("without correction", False), ("with correction", True)):
        allowed = frozenset({"billing"})
        llm = MockLLM(confused_technical)
        agent_llm = GraphAwareLLM(llm, allowed) if wrap else llm
        agents = {**AGENTS, "technical": Agent("technical", agent_llm, "Bugs.", allowed), "billing": SLA_BILLING}
        rt = HandoffRuntime(agents, entry="technical")
        conv = rt.start()
        trace.note(f"-- {label}")
        rt.user_says(conv, "The outage cost us a day. I want a refund.", trace)
        trace.note(f"escalated={conv.escalated}, owner={conv.owner}")
    trace.print()
    assert not conv.escalated and conv.owner == "billing"


if __name__ == "__main__":
    main()
