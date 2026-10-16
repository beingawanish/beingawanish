"""Memory tiers demo: three sessions, three separate processes, one JSON file.

Run:  python3 code/patterns/memory_tiers/main.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.memory_tiers.memory import MemoryManager  # noqa: E402

extractor = MockLLM(rules([
    (lambda p, s: "I'm Ana" in p,
     '[{"key": "name", "value": "Ana", "tags": ["profile"], "durability": "stable", "confidence": 0.95},'
     ' {"key": "diet", "value": "vegetarian", "tags": ["food"], "durability": "stable", "confidence": 0.9},'
     ' {"key": "allergy", "value": "peanuts", "tags": ["food", "health"], "durability": "stable", "confidence": 0.95}]'),
    (lambda p, s: "in Porto" in p,
     '[{"key": "location_this_week", "value": "Porto", "tags": ["travel"], "durability": "transient", "confidence": 0.9}]'),
    (lambda p, s: "might like Thai" in p,
     '[{"key": "cuisine", "value": "Thai", "tags": ["food"], "durability": "stable", "confidence": 0.45}]'),
    (lambda p, s: "eat fish now" in p,
     '[{"key": "diet", "value": "pescatarian", "tags": ["food"], "durability": "stable", "confidence": 0.9}]'),
    (lambda p, s: True, "[]"),
]))


def run_session(path, session, turns, trace):
    mm = MemoryManager(extractor, path, working_turns=2)  # a fresh process: only the file carries over
    for turn in turns:
        for d in mm.observe(turn, session):
            trace.step(f"{session} write", f"{d.key}={d.value} -> {d.tier} ({d.reason})")
    return mm


def main() -> None:
    trace = Trace("Memory tiers")
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "memory.json"
        trace.note("-- session s1")
        mm = run_session(path, "s1", ["Hi, I'm Ana. I'm vegetarian and allergic to peanuts.",
                                      "This week I'm in Porto for work.",
                                      "I think I might like Thai food?"], trace)
        trace.step("s1 working", f"last 2 turns only: {list(mm.working.turns)[0][:22]}… | {list(mm.working.turns)[1][:22]}…")

        trace.note("-- session s2 (new process): 'Suggest a dinner recipe'")
        mm = MemoryManager(extractor, path)
        facts = mm.semantic.recall(["food"])
        trace.step("s2 recall", ", ".join(f"{f.key}={f.value}" for f in facts))
        trace.step("s2 episodic", f"search 'Porto' -> {[e['text'] for e in mm.episodic.search(['Porto'])]}")
        run_session(path, "s2", ["Actually, I eat fish now."], trace)

        trace.note("-- session s3 (new process)")
        mm = MemoryManager(extractor, path)
        diet = mm.semantic.get("diet")
        trace.step("s3 recall", f"diet={diet.value} (history: {[h['value'] for h in diet.history]}, "
                                f"source: {diet.source!r})")
        trace.step("s3 store", f"{len(mm.store.semantic)} semantic facts, {len(mm.store.episodic)} episodic notes")
    trace.print()

    assert [f.key for f in facts] == ["allergy", "diet"] and diet.value == "pescatarian"
    assert diet.history == [{"value": "vegetarian", "session": "s1"}]


if __name__ == "__main__":
    main()
