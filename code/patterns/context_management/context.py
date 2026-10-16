"""Context management: assemble each call's context under a token budget.

Four levers, applied in a fixed order of priority:
1. Pin      — system rules and the task are always included verbatim.
2. Disclose — tools appear as a one-line index; full docs load only when asked for.
3. Compact  — old transcript turns are folded into a running summary; recent turns stay verbatim.
4. Evict    — reference documents are added by relevance until the budget is reached.

Every assembly returns a report saying what was kept, compacted and evicted, so
context decisions are observable. Reused by the coding-team capstone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM
from agentkit.llm import _tokens as tokens


@dataclass
class ContextReport:
    sections: dict[str, int] = field(default_factory=dict)  # section -> tokens
    compacted_turns: int = 0
    evicted_docs: list[str] = field(default_factory=list)
    loaded_tool_docs: list[str] = field(default_factory=list)
    over_budget: bool = False  # pinned + recent alone exceeded the budget: a design problem, surfaced

    @property
    def total(self) -> int:
        return sum(self.sections.values())


class ContextManager:
    def __init__(self, budget: int, summarizer: LLM, keep_recent: int = 4, min_relevance: float = 0.5) -> None:
        self.budget, self.summarizer, self.keep_recent = budget, summarizer, keep_recent
        self.min_relevance = min_relevance
        self.summary = ""
        self.summarized_upto = 0  # transcript turns already folded into the summary
        self.summarizer_calls = 0

    def _compact(self, transcript: list[str]) -> list[str]:
        cut = max(0, len(transcript) - self.keep_recent)
        if cut > self.summarized_upto:  # summarise only turns not yet folded in (incremental)
            new = "\n".join(transcript[self.summarized_upto:cut])
            self.summary = self.summarizer.complete(
                f"COMPACT. Update the running summary with these turns. Keep decisions, facts, ids, open items.\n"
                f"Summary so far: {self.summary or '(none)'}\nNew turns:\n{new}").strip()
            self.summarized_upto = cut
            self.summarizer_calls += 1
        return transcript[cut:]

    def assemble(self, system: str, task: str, tools: dict[str, tuple[str, str]], loaded: set[str],
                 transcript: list[str], docs: list[tuple[str, float, str]]) -> tuple[str, ContextReport]:
        """tools: name -> (one-line description, full docs). docs: (id, relevance, text)."""
        rep = ContextReport()
        parts: list[tuple[str, str]] = [("system", system), ("task", f"TASK: {task}")]
        index = "\n".join(f"- {n}: {short}" + ("" if n in loaded else " (call help(name) for docs)")
                          for n, (short, _) in tools.items())
        full = "\n".join(f"## {n}\n{tools[n][1]}" for n in sorted(loaded) if n in tools)
        rep.loaded_tool_docs = sorted(loaded)
        parts.append(("tools", "TOOLS:\n" + index + ("\n" + full if full else "")))
        recent = self._compact(transcript)
        rep.compacted_turns = self.summarized_upto
        if self.summary:
            parts.append(("summary", f"EARLIER (summary): {self.summary}"))
        parts.append(("recent", "RECENT:\n" + "\n".join(recent)))
        used = sum(tokens(t) for _, t in parts)
        kept = []
        rep.over_budget = used > self.budget
        for doc_id, rel, text in sorted(docs, key=lambda d: -d[1]):
            cost = tokens(text)
            if rel < self.min_relevance:
                rep.evicted_docs.append(f"{doc_id} (relevance {rel:.2f})")
            elif used + cost > self.budget:
                rep.evicted_docs.append(f"{doc_id} (budget)")
            else:
                kept.append(f"[{doc_id}] {text}")
                used += cost
        if kept:
            parts.append(("docs", "REFERENCE:\n" + "\n".join(kept)))
        rep.sections = {name: tokens(text) for name, text in parts}
        return "\n\n".join(t for _, t in parts), rep


def naive_prompt(system: str, task: str, tools: dict[str, tuple[str, str]], transcript: list[str],
                 docs: list[tuple[str, float, str]]) -> str:
    """Everything, verbatim — the baseline context management is measured against."""
    return "\n\n".join([system, f"TASK: {task}",
                        "\n".join(f"## {n}: {s}\n{d}" for n, (s, d) in tools.items()),
                        "\n".join(transcript), "\n".join(t for _, _, t in docs)])


def loop_render(cm: ContextManager, task: str, tools: dict[str, tuple[str, str]], loaded: Optional[set[str]] = None,
                docs: Optional[list[tuple[str, float, str]]] = None, log: Optional[list[ContextReport]] = None):
    """Adapter: a ``render`` function for the tool-use loop (#9) backed by a ContextManager."""
    def render(system: str, _specs: str, transcript: list[dict]) -> str:
        from patterns.tool_use_loop.loop import PROTOCOL
        lines = [f"{m['role'].upper()}: {m['content']}" for m in transcript]
        prompt, rep = cm.assemble(system + "\n" + PROTOCOL, task, tools, loaded or set(), lines, docs or [])
        if log is not None:
            log.append(rep)
        return prompt
    return render
