"""Agentic RAG: retrieval as a decision inside the loop.

The agent decides *whether* to retrieve, writes the query, grades what came back,
reformulates when evidence is insufficient, and answers only from graded evidence
with citations that code verifies. If evidence never becomes sufficient, it
abstains instead of guessing.

Reused by the deep-research capstone (one call per sub-question).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace, extract_json

STOP = {"a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are", "be", "can", "i", "my",
        "do", "you", "your", "it", "with", "after", "what", "how", "does", "any", "we", "our",
        "get", "give", "given", "say"}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOP]


class Retriever:
    """Tiny TF-IDF retriever. Deterministic; good enough to show the pattern."""

    def __init__(self, docs: dict[str, str]) -> None:
        self.docs = docs
        self.tf = {d: Counter(tokenize(t)) for d, t in docs.items()}
        n = len(docs)
        df = Counter(w for c in self.tf.values() for w in c)
        self.idf = {w: math.log((n + 1) / (c + 0.5)) for w, c in df.items()}

    def search(self, query: str, k: int = 2) -> list[tuple[str, float]]:
        q = tokenize(query)
        scored = [(d, sum(self.idf.get(w, 0) * tf[w] for w in q)) for d, tf in self.tf.items()]
        scored = [(d, round(s, 2)) for d, s in scored if s > 0]
        return sorted(scored, key=lambda x: (-x[1], x[0]))[:k]


@dataclass
class RagResult:
    answer: Optional[str]
    stop_reason: str  # "direct" | "answered" | "abstained"
    citations: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    evidence: dict[str, str] = field(default_factory=dict)


CITE = re.compile(r"\[([\w-]+)\]")


def agentic_rag(llm: LLM, retriever: Retriever, question: str, max_queries: int = 3, k: int = 2,
                trace: Optional[Trace] = None, skip_route: bool = False) -> RagResult:
    if not skip_route:
        route = llm.complete(f"ROUTE: Does answering this need our knowledge base? Reply RETRIEVE or DIRECT.\n"
                             f"Question: {question}").strip().upper()
        if trace:
            trace.step("route", route)
        if route.startswith("DIRECT"):
            ans = llm.complete(f"ANSWER directly: {question}").strip()
            if trace:
                trace.step("answer", ans)
            return RagResult(ans, "direct")

    res = RagResult(None, "abstained")
    missing = ""
    for _ in range(max_queries):
        query = llm.complete(f"QUERY for: {question}\nPrevious queries: {res.queries}\nStill missing: {missing}").strip()
        res.queries.append(query)
        hits = retriever.search(query, k)
        if trace:
            trace.step(f"query {len(res.queries)}", f"{query!r} -> {[d for d, _ in hits] or 'no hits'}")
        if not hits:
            missing = "nothing matched that query"
            continue
        passages = "\n".join(f"[{d}] {retriever.docs[d]}" for d, _ in hits)
        try:
            grade = extract_json(llm.complete(
                f"GRADE passages for: {question}\n{passages}\n"
                'Reply {"relevant": [ids], "sufficient": bool, "missing": "<what is still unknown>"}'))
            relevant = [d for d in grade.get("relevant", []) if d in dict(hits)]
            sufficient, missing = bool(grade.get("sufficient")), str(grade.get("missing", ""))
        except (ValueError, AttributeError):
            relevant, sufficient, missing = [], False, "grader output unusable"
        for d in relevant:
            res.evidence[d] = retriever.docs[d]
        if trace:
            trace.step("grade", f"relevant={relevant} sufficient={sufficient}" + (f" missing={missing!r}" if not sufficient else ""))
        if sufficient and res.evidence:
            evidence = "\n".join(f"[{d}] {t}" for d, t in res.evidence.items())
            ans = llm.complete(f"ANSWER using ONLY this evidence; cite ids like [id].\n{evidence}\nQuestion: {question}").strip()
            cited = CITE.findall(ans)
            if cited and all(c in res.evidence for c in cited):  # citation check in code
                res.answer, res.stop_reason, res.citations = ans, "answered", cited
                if trace:
                    trace.step("answer", ans)
                return res
            if trace:
                trace.step("reject", f"citations {cited} not all in evidence {list(res.evidence)}")
            missing = "answer cited sources that were not retrieved"
    res.answer = "I couldn't find this in our documentation, so I won't guess. A specialist can confirm."
    if trace:
        trace.step("abstain", res.answer)
    return res
