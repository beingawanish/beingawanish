"""Routing: classify once, dispatch to exactly one specialised path.

Two-stage classifier: a free keyword pre-filter handles unambiguous inputs; the LLM
classifies the rest. Any LLM answer that is unparseable, names an unknown route, or
falls below the confidence threshold goes to the fallback route.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from agentkit import LLM, extract_json

CLASSIFY_SYSTEM = "You are a ticket classifier. Reply with JSON only."


@dataclass
class Decision:
    route: str
    confidence: float
    method: str  # "keyword" | "llm" | "fallback"
    reason: str = ""


class Router:
    def __init__(
        self,
        llm: LLM,
        routes: dict[str, str],  # route name -> one-line description shown to the classifier
        fallback: str,
        threshold: float = 0.7,
        keywords: Optional[dict[str, list[str]]] = None,
    ) -> None:
        if fallback not in routes:
            raise ValueError("fallback must be one of the routes")
        self.llm, self.routes, self.fallback = llm, routes, fallback
        self.threshold, self.keywords = threshold, keywords or {}

    def _keyword(self, text: str) -> Optional[str]:
        low = text.lower()
        hits = {r for r, words in self.keywords.items() if any(w in low for w in words)}
        return hits.pop() if len(hits) == 1 else None  # ambiguous or none -> ask the LLM

    def classify(self, text: str) -> Decision:
        route = self._keyword(text)
        if route:
            return Decision(route, 1.0, "keyword", "unique keyword match")

        menu = "\n".join(f"- {name}: {desc}" for name, desc in self.routes.items())
        prompt = (
            f"Classify the ticket into exactly one route.\nRoutes:\n{menu}\n\n"
            f'Ticket: """{text}"""\n\nReply as {{"route": "<name>", "confidence": <0..1>}}'
        )
        raw = self.llm.complete(prompt, system=CLASSIFY_SYSTEM)
        try:
            route, conf = self.parse(raw)
        except (ValueError, KeyError, TypeError) as exc:
            return Decision(self.fallback, 0.0, "fallback", f"unparseable classifier output ({exc})")
        if route not in self.routes:
            return Decision(self.fallback, conf, "fallback", f"unknown route '{route}'")
        if conf < self.threshold:
            return Decision(self.fallback, conf, "fallback", f"low confidence for '{route}'")
        return Decision(route, conf, "llm")

    def parse(self, raw: str) -> tuple[str, float]:
        """Turn raw classifier text into (route, confidence). Override to normalise."""
        data = extract_json(raw)
        return str(data["route"]), float(data["confidence"])

    def dispatch(self, text: str, handlers: dict[str, Callable[[str], str]]) -> tuple[Decision, str]:
        decision = self.classify(text)
        return decision, handlers[decision.route](text)
