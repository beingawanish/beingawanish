"""Exercise solution — Memory tiers.

Task: a user says "forget my allergy". Deleting the current value is not enough —
the superseded history and any episodic notes can still leak it. Implement
`forget(key)` that removes the fact *and its history*, scrubs episodic notes that
mention the key, and leaves a tombstone (no value) so a later extraction from old
context does not silently re-add it.

Run:  python3 code/patterns/memory_tiers/exercise_solution.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.memory_tiers.memory import SemanticMemory, Store  # noqa: E402


def forget(store: Store, key: str) -> None:
    store.semantic.pop(key, None)
    store.episodic = [e for e in store.episodic if not e["text"].startswith(f"{key}=")]
    store.episodic.append({"session": "-", "text": f"TOMBSTONE {key}"})
    store.save()


class RespectfulSemanticMemory(SemanticMemory):
    def upsert(self, key, value, tags, source, session):
        if any(e["text"] == f"TOMBSTONE {key}" for e in self.store.episodic) and "remember" not in source.lower():
            return "blocked (user asked to forget)"
        return super().upsert(key, value, tags, source, session)


def main() -> None:
    trace = Trace("Memory tiers — exercise solution")
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(pathlib.Path(tmp) / "m.json")
        mem = RespectfulSemanticMemory(store)
        mem.upsert("allergy", "peanuts", ["food"], "I'm allergic to peanuts", "s1")
        mem.upsert("allergy", "peanuts, shellfish", ["food"], "also shellfish", "s2")
        store.episodic.append({"session": "s2", "text": "allergy=shellfish (mentioned at dinner)"})
        forget(store, "allergy")
        reloaded = Store(pathlib.Path(tmp) / "m.json")
        leaks = [e for e in reloaded.episodic if "shellfish" in e["text"] or "peanut" in e["text"]]
        trace.step("after forget", f"semantic has allergy={('allergy' in reloaded.semantic)}; episodic leaks={len(leaks)}")
        status = RespectfulSemanticMemory(reloaded).upsert("allergy", "peanuts", ["food"], "old transcript replay", "s3")
        trace.step("replayed extraction", status)
        status = RespectfulSemanticMemory(reloaded).upsert("allergy", "sesame", ["food"], "Please remember I'm allergic to sesame", "s4")
        trace.step("explicit new request", status)
    trace.print()
    assert not leaks


if __name__ == "__main__":
    main()
