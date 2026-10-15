"""Sequential handoffs: agents transfer *ownership* of a live conversation.

Exactly one agent owns the conversation at a time. The owner either replies to the
user or hands off with an explicit Handoff object (target, reason, summary). There
is no coordinator: the runtime only enforces the allowed handoff graph, a per-turn
handoff cap, and a ping-pong guard that escalates to a human.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json


@dataclass
class Handoff:
    source: str
    target: str
    reason: str
    summary: str


@dataclass
class Agent:
    name: str
    llm: LLM
    instructions: str
    can_handoff_to: frozenset[str] = frozenset()


@dataclass
class Conversation:
    owner: str
    transcript: list[str] = field(default_factory=list)
    handoffs: list[Handoff] = field(default_factory=list)
    escalated: bool = False


class HandoffRuntime:
    def __init__(self, agents: dict[str, Agent], entry: str, max_handoffs_per_turn: int = 3) -> None:
        self.agents, self.entry, self.max_handoffs = agents, entry, max_handoffs_per_turn

    def start(self) -> Conversation:
        return Conversation(owner=self.entry)

    def user_says(self, conv: Conversation, message: str, trace: Optional[Trace] = None) -> str:
        conv.transcript.append(f"USER: {message}")
        visited = [conv.owner]
        incoming: Optional[Handoff] = None
        for _ in range(self.max_handoffs + 1):
            agent = self.agents[conv.owner]
            brief = (f"HANDOFF from {incoming.source}: {incoming.reason}. Summary: {incoming.summary}\n"
                     if incoming else "")
            raw = agent.llm.complete(
                f"{brief}Conversation:\n" + "\n".join(conv.transcript[-6:]) +
                f"\nYou may hand off to: {sorted(agent.can_handoff_to) or 'nobody'}.\n"
                'Reply {"reply": "..."} or {"handoff_to": "<agent>", "reason": "...", "summary": "..."}',
                system=f"You are the {agent.name} agent. {agent.instructions}")
            msg = extract_json(raw)
            if "reply" in msg:
                conv.transcript.append(f"{agent.name.upper()}: {msg['reply']}")
                if trace:
                    trace.step(agent.name, msg["reply"])
                return msg["reply"]
            target = str(msg.get("handoff_to"))
            if target not in agent.can_handoff_to:
                return self._escalate(conv, f"{agent.name} tried to hand off to '{target}' (not allowed)", trace)
            if target in visited:
                return self._escalate(conv, f"ping-pong: {' → '.join(visited + [target])}", trace)
            incoming = Handoff(agent.name, target, str(msg.get("reason", "")), str(msg.get("summary", "")))
            conv.handoffs.append(incoming)
            conv.owner = target
            visited.append(target)
            if trace:
                trace.step(f"{agent.name} ⇒ {target}", f"{incoming.reason} | summary: {incoming.summary}")
        return self._escalate(conv, f"more than {self.max_handoffs} handoffs in one turn", trace)

    def _escalate(self, conv: Conversation, why: str, trace: Optional[Trace]) -> str:
        conv.escalated = True
        reply = "I'm bringing in a human colleague to sort this out — they'll have the full conversation."
        conv.transcript.append(f"SYSTEM: escalated ({why})")
        if trace:
            trace.step("escalate", why)
        return reply
