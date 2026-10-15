"""Memory tiers: separate what an agent remembers by lifetime and access path.

* Working memory  — the last N turns, verbatim, always in context.
* Episodic memory — per-session summaries and transient facts; searched on demand.
* Semantic memory — durable facts (key -> value) with provenance and history.

The model *proposes* memories; code *decides* what is written (write policy), how
conflicts resolve (newer supersedes, history kept), and what is recalled (by tag).
Long-term tiers persist to a JSON file, so memory survives a restart.

Canonical module: the deep-research capstone stores findings in SemanticMemory.
"""

from __future__ import annotations

import json
import pathlib
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, extract_json


class WorkingMemory:
    def __init__(self, max_turns: int = 4) -> None:
        self.turns: deque[str] = deque(maxlen=max_turns)

    def add(self, turn: str) -> None:
        self.turns.append(turn)

    def render(self) -> str:
        return "\n".join(self.turns)


@dataclass
class Fact:
    key: str
    value: str
    tags: list[str]
    source: str
    session: str
    history: list[dict] = field(default_factory=list)  # superseded values, oldest first


class Store:
    """Persistence for the two long-term tiers."""

    def __init__(self, path: pathlib.Path | str) -> None:
        self.path = pathlib.Path(path)
        data = json.loads(self.path.read_text()) if self.path.exists() else {"semantic": {}, "episodic": []}
        self.semantic = {k: Fact(**v) for k, v in data["semantic"].items()}
        self.episodic: list[dict] = data["episodic"]

    def save(self) -> None:
        data = {"semantic": {k: vars(f) for k, f in self.semantic.items()}, "episodic": self.episodic}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        tmp.replace(self.path)


class SemanticMemory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def upsert(self, key: str, value: str, tags: list[str], source: str, session: str) -> str:
        old = self.store.semantic.get(key)
        if old and old.value == value:
            return "unchanged"
        fact = Fact(key, value, sorted(set(tags)), source, session)
        if old:
            fact.history = old.history + [{"value": old.value, "session": old.session}]
        self.store.semantic[key] = fact
        self.store.save()
        return "updated" if old else "added"

    def recall(self, tags: list[str], k: int = 5) -> list[Fact]:
        want = set(tags)
        hits = [f for f in self.store.semantic.values() if want & set(f.tags)]
        return sorted(hits, key=lambda f: f.key)[:k]

    def get(self, key: str) -> Optional[Fact]:
        return self.store.semantic.get(key)


class EpisodicMemory:
    def __init__(self, store: Store) -> None:
        self.store = store

    def note(self, session: str, text: str) -> None:
        self.store.episodic.append({"session": session, "text": text})
        self.store.save()

    def search(self, words: list[str]) -> list[dict]:
        return [e for e in self.store.episodic if any(w.lower() in e["text"].lower() for w in words)]


@dataclass
class WriteDecision:
    key: str
    value: str
    tier: str  # "semantic" | "episodic" | "dropped"
    reason: str


class MemoryManager:
    """The write policy lives here, in code — not in the extraction prompt."""

    def __init__(self, llm: LLM, path: pathlib.Path | str, min_confidence: float = 0.7, working_turns: int = 4) -> None:
        self.llm = llm
        self.store = Store(path)
        self.working = WorkingMemory(working_turns)
        self.semantic = SemanticMemory(self.store)
        self.episodic = EpisodicMemory(self.store)
        self.min_confidence = min_confidence

    def observe(self, turn: str, session: str) -> list[WriteDecision]:
        self.working.add(turn)
        raw = self.llm.complete(
            "EXTRACT memory candidates from this user turn as a JSON list of "
            '{"key", "value", "tags", "durability": "stable"|"transient", "confidence": 0..1}.\n'
            f"Turn: {turn}")
        try:
            candidates = extract_json(raw)
        except ValueError:
            candidates = []
        decisions = []
        for c in candidates if isinstance(candidates, list) else []:
            key, value = str(c.get("key", "")), str(c.get("value", ""))
            conf, durable = float(c.get("confidence", 0)), c.get("durability") == "stable"
            if not key or conf < self.min_confidence:
                decisions.append(WriteDecision(key, value, "dropped", f"confidence {conf:.2f} < {self.min_confidence}"))
            elif durable:
                status = self.semantic.upsert(key, value, list(c.get("tags", [])), source=turn, session=session)
                decisions.append(WriteDecision(key, value, "semantic", status))
            else:
                self.episodic.note(session, f"{key}={value}")
                decisions.append(WriteDecision(key, value, "episodic", "transient"))
        return decisions
