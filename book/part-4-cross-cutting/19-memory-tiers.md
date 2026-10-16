# 19. Memory tiers

> **Intent.** Separate what an agent remembers by lifetime and access path (working memory in context, episodic notes per session, durable semantic facts with history) and let code, not the model, decide what gets written, how conflicts resolve, and what gets recalled.

**Also known as:** long-term memory, agent memory, user memory · **Part:** 4 — Cross-cutting · **Code:** `code/patterns/memory_tiers/` *(canonical module, imported by the deep-research capstone)*

## Structure

![Memory tiers structure](../diagrams/memory_tiers.svg)

Each user turn enters **working memory**, a bounded window of the last *N* turns, verbatim. An extractor model proposes memory candidates: key, value, tags, durability and confidence. A **code write policy** sends stable, confident facts to **semantic memory** (with source, session and history), transient facts to **episodic memory**, and drops the rest. Long-term tiers persist to disk; recall is by tag.

## Design concept & theory

**Core idea.** Human memory is not one store, and agent memory should not be either. "I'm vegetarian" should be remembered for months. "I'm in Porto this week" for days. "I think I might like Thai?" probably not at all. A single "memory" list that keeps everything gets both noisy and stale.

**Why tiers work.**

- *Different lifetimes need different stores.* Working memory is cheap and exact but small. Episodic memory is cheap to write and searched only on demand. Semantic memory is curated, small, high-precision and always worth recalling. Each tier has its own write cost, recall cost and staleness risk.
- *The write policy is the quality control.* Models extract candidates eagerly. Code applies the policy: a confidence floor, a durability check, and later on a PII filter. In the example, the 0.45-confidence Thai preference is dropped and the transient Porto location goes to episodic notes only. What is *not* remembered matters as much as what is.
- *Facts change; history must not vanish.* "Vegetarian" becomes "pescatarian". Overwriting loses the audit trail, while appending creates contradictions. Superseding with history (the current value plus prior values and their sessions) gives both a clean current answer and the record.
- *Provenance enables trust and deletion.* Every fact keeps the turn it came from. You can show users why the agent believes something, and delete it properly when asked (the exercise).

**Invariants.** (1) At least two tiers with different lifetimes. (2) Writes go through a code policy. (3) Updates supersede with history and provenance. (4) Long-term tiers survive restarts.

**Lineage.** Cognitive psychology's working, episodic and semantic memory (Tulving, 1972); the memory hierarchy in computer architecture (registers, cache, disk); event sourcing for history.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The same user or project returns across sessions. | Interactions are one-off and stateless. |
| Repeating questions or re-doing work is costly (the research capstone). | The "memory" is really a document corpus. Use [agentic RAG (#10)](../part-2-single-agent/10-agentic-rag.md). |
| Personal facts must persist, update and be deletable. | You cannot meet privacy obligations for stored personal data. |
| You need to explain why the agent knows something. | The full history fits in context. Keep it simple. |

**Cheaper alternative:** keep the last *N* turns verbatim and a single running summary (working memory plus compaction from [#20](20-context-management.md)). Upgrade when facts must outlive sessions, change over time, or be individually recalled and deleted.

## Forces & trade-offs

| Force | vs. no persistent memory | Why |
|---|---|---|
| Latency | ≈ | Extraction can run asynchronously; recall is a lookup. |
| Cost | ↑ small | One extraction call per turn, often on a small model; saved repeat work can outweigh it. |
| Reliability | ↑ personalisation and continuity; ↓ if the policy is weak | Stale or wrong memories are worse than none. |
| Complexity | ↑ | Policy, schema, persistence, conflict resolution, deletion. |

## Trade-off analysis & usage guidance

**Model.** Write cost ≈ one extraction call per turn (or per session, batched). Recall cost ≈ a lookup plus the tokens of recalled facts in context. The payoff is avoided work: in the deep-research capstone, the follow-up session made 0 retrieval-agent calls where the first session made 14.

**Decision checklist.**

1. Which facts are durable, which are transient, and which should never be stored?
2. What is the confidence floor, and who calibrates it?
3. How do updates resolve: supersede, keep history, ask the user?
4. How is recall scoped: by tag, by user, by recency? How many facts at most?
5. How does a user see and delete what is remembered?

**Usage in production.**

- Run extraction on a small model, asynchronously after the turn.
- Cap recalled facts per call, and prefer specific tags over "recall everything".
- Expire episodic notes on a schedule. Transient facts should not quietly become permanent.
- Log every write with its policy decision. Dropped candidates are your tuning data.
- Never store secrets or credentials, and filter PII by policy.

## Worked example

### Example first: what happens

```
python3 code/patterns/memory_tiers/main.py
```

<!-- expected-output: code/patterns/memory_tiers/main.py -->
```text
Memory tiers
============
-- session s1
[s1 write] name=Ana -> semantic (added)
[s1 write] diet=vegetarian -> semantic (added)
[s1 write] allergy=peanuts -> semantic (added)
[s1 write] location_this_week=Porto -> episodic (transient)
[s1 write] cuisine=Thai -> dropped (confidence 0.45 < 0.7)
[s1 working] last 2 turns only: This week I'm in Porto… | I think I might like T…
-- session s2 (new process): 'Suggest a dinner recipe'
[s2 recall] allergy=peanuts, diet=vegetarian
[s2 episodic] search 'Porto' -> ['location_this_week=Porto']
[s2 write] diet=pescatarian -> semantic (updated)
-- session s3 (new process)
[s3 recall] diet=pescatarian (history: ['vegetarian'], source: 'Actually, I eat fish now.')
[s3 store] 3 semantic facts, 1 episodic notes
```

**Session s1:** three turns produce five candidates. Name, diet and allergy are stable and confident, so they go to semantic memory. The location is transient, so it becomes an episodic note. The Thai guess falls below the confidence floor and is dropped. Working memory keeps only the last two turns.

**Session s2** is a new process, with only the file carried over. A dinner request recalls by tag `food`: the allergy and diet, nothing else. The Porto note is findable in episodic memory but is not volunteered. "Actually, I eat fish now" *updates* the diet.

**Session s3:** the diet is `pescatarian`, with `vegetarian` in its history and the source sentence attached.

### Why first: why it is built this way

- **The extractor proposes; `MemoryManager.observe` disposes.** The prompt asks for candidates with durability and confidence. The policy (floor, durability routing) is ten lines of code you can test without a model.
- **`upsert` returns `added`, `updated` or `unchanged`.** Identical re-statements do not churn history, and every write is classified for logging.
- **Tags drive recall.** A dinner request needs food facts, not the user's name or travel. Tag recall is crude and predictable; embeddings are a drop-in upgrade for larger stores.
- **Atomic file writes.** Temp file, then rename, so a crash cannot corrupt the store, the same as the [HITL queue](../part-3-multi-agent/17-human-in-the-loop.md).

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Memory pollution | Guesses and jokes stored as facts. | Confidence floor; durability classification; user confirmation for sensitive keys. |
| Stale facts | Old preferences override new ones. | Supersede with history; recency wins; periodic review. |
| Contradictions | Two values for one key. | One key, one current value; history for the rest. |
| Over-recall | Every fact injected into every prompt. | Tag-scoped recall; per-call cap. |
| Privacy leak | Deleted data survives in history or notes. | Forget removes history, scrubs notes, and leaves a tombstone (exercise). |
| Cross-user bleed | One user's memory recalled for another. | Partition stores by user or tenant; test it. |

## Variations

- **Procedural memory.** Store *how-to* lessons learned from failures (see the [reflection](../part-2-single-agent/08-reflection.md) exercise).
- **Embedding-based recall.** Semantic similarity instead of tags, for large or unstructured stores.
- **User-editable memory.** Show the semantic store to the user, who can correct or delete entries.
- **Shared team memory.** A project-level store several agents read and write, with stricter write policies.

## Try it

A user says "forget my allergy". Deleting the current value is not enough: superseded history and episodic notes still contain it. Implement `forget(key)` that removes the fact *and its history*, scrubs episodic notes about it, and leaves a **tombstone**, so that a replayed old transcript cannot silently re-add it while a new, explicit request still can.

→ Solution: [Solutions — Memory tiers](../solutions/19-memory-tiers.md)

## 60-second interview lens

- **Say:** "Memory tiers split agent memory by lifetime: working memory in context, episodic notes per session, and durable semantic facts with history and provenance, with code owning the write policy and recall."
- **Trade-off to name:** continuity and less repeated work, against the risk of stale or polluted memories and real privacy obligations. The write policy is where quality is won.
- **Expect the follow-up:** "Memory or RAG?" RAG reads an external corpus you don't own; memory is the agent's own history, which it writes, updates and must be able to delete.
- **Red flag to avoid:** letting the model decide what to store with no policy, confidence floor or deletion path.

## Related patterns

- [Context management (#20)](20-context-management.md): what fits in *this* call; memory is what persists *across* calls.
- [Agentic RAG (#10)](../part-2-single-agent/10-agentic-rag.md): retrieval over a corpus the agent does not own.
- [Reflection (#8)](../part-2-single-agent/08-reflection.md): trajectory lessons are a kind of procedural memory.
- [Deep-research capstone](../capstones/deep-research.md): findings stored and reused across sessions.
