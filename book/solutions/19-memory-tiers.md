# Solution — 19. Memory tiers

**Exercise.** Forget a fact completely, and keep it forgotten.

**Approach.** Three parts. Remove the semantic fact (its history goes with it). Scrub episodic notes written about the key. Leave a tombstone, so that the write path can refuse silent re-adds while still allowing an explicit new request.

```python
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
```

Run: `python3 code/patterns/memory_tiers/exercise_solution.py`

<!-- expected-output: code/patterns/memory_tiers/exercise_solution.py -->
```text
Memory tiers — exercise solution
================================
[after forget] semantic has allergy=False; episodic leaks=0
[replayed extraction] blocked (user asked to forget)
[explicit new request] added
```

**Discussion.** The tombstone records *that* something was forgotten, never *what*. The "remember" keyword check is a stand-in for real intent detection; in production, re-adding a forgotten fact should need an explicit user action in the UI. Remember also the copies outside the memory store: logs, caches and eval sets. A deletion request covers those too.
