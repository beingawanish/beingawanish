"""Debate / peer critique: symmetric peers argue over rounds; a judge resolves.

Each debater sees the question, its assigned position, and the opponents' latest
arguments, and may concede. If everyone agrees, the debate stops early (no judge
call). Otherwise a judge reads the transcript and decides with a rationale that must
reference the arguments it relied on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json


@dataclass
class Debater:
    name: str
    llm: LLM
    position: str


@dataclass
class DebateResult:
    decision: str
    rationale: str
    rounds: int
    consensus: bool
    transcript: list[tuple[int, str, str]] = field(default_factory=list)  # (round, debater, argument)


def debate(debaters: list[Debater], judge: LLM, question: str, rounds: int = 2,
           trace: Optional[Trace] = None) -> DebateResult:
    transcript: list[tuple[int, str, str]] = []
    for rnd in range(1, rounds + 1):
        latest = {n: a for r, n, a in transcript if r == rnd - 1}
        agreed = []
        for d in debaters:
            others = "\n".join(f"{n}: {a}" for n, a in latest.items() if n != d.name) or "(opening round)"
            msg = extract_json(d.llm.complete(
                f"DEBATE round {rnd}: {question}\nYour position: {d.position}\nOpponents said:\n{others}\n"
                'Reply {"argument": "...", "agree_with_opponents": bool}',
                system=f"You are {d.name}. Argue honestly; concede if persuaded."))
            transcript.append((rnd, d.name, str(msg["argument"])))
            agreed.append(bool(msg.get("agree_with_opponents")))
            if trace:
                trace.step(f"r{rnd} {d.name}", str(msg["argument"]))
        if all(agreed):
            if trace:
                trace.step("consensus", f"all debaters agree after round {rnd} — no judge needed")
            return DebateResult(transcript[-1][2], "consensus of debaters", rnd, True, transcript)
    text = "\n".join(f"[r{r}] {n}: {a}" for r, n, a in transcript)
    verdict = extract_json(judge.complete(
        f"JUDGE the debate: {question}\n{text}\n"
        'Reply {"decision": "...", "rationale": "... cite the arguments you relied on ..."}',
        system="You are an impartial judge. Weigh arguments, not eloquence or order."))
    if trace:
        trace.step("judge", f"{verdict['decision']} — {verdict['rationale']}")
    return DebateResult(str(verdict["decision"]), str(verdict["rationale"]), rounds, False, transcript)
