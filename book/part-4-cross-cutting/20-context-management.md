# 20. Context management (compaction and progressive disclosure)

> **Intent.** Assemble every model call's context deliberately under a token budget: pin what must always be there, disclose tool and document detail only when needed, compact old conversation into a running summary, and evict low-value material, with a report of every decision.

**Also known as:** context engineering, prompt budgeting, compaction · **Part:** 4 — Cross-cutting · **Code:** `code/patterns/context_management/` *(imported by the coding-team capstone)*

## Structure

![Context management structure](../diagrams/context_management.svg)

Four levers, applied in priority order:

- **Pin:** system rules and the task are always included, verbatim.
- **Disclose:** tools appear as a one-line index; full docs load only for tools the model asked about.
- **Compact:** old turns are folded into a running summary by a small model, and recent turns stay verbatim.
- **Evict:** reference documents are added by relevance (above a floor) until the budget is reached.

Every assembly returns a report: section sizes, compacted turns, evicted documents, loaded tool docs, and whether the pinned parts alone exceeded the budget.

## Design concept & theory

**Core idea.** The context window is the agent's working memory, and it is finite, priced per token, and sensitive to noise. Long-running agents fail less from lack of intelligence than from context that is too long, too noisy, or missing the one fact that mattered. Context management treats each prompt as an *assembled artefact* with a budget, not as a log you keep appending to.

**Why it works.**

- *Relevance beats completeness.* Including a 25-paragraph style guide in an incident rollback prompt costs tokens and attention and adds nothing. Relevance-ranked inclusion with a floor drops it. In the example, two of three documents are evicted for low relevance, not just for size.
- *Progressive disclosure keeps the menu cheap.* Six tools at full documentation would dominate the prompt. Six one-liners cost little, and the model asks for the one it needs (`help(deploy)`). This is lazy loading for prompts.
- *Compaction converts growth from linear to roughly constant.* Without it, prompt size grows with every turn. With a running summary plus the last *k* turns, size stays roughly flat. The summary is updated *incrementally* (only new turns are summarised), so compaction costs one small call per *k* turns, not one per call.
- *Pinning protects what must never be lost.* Rules ("never deploy on Fridays without a ticket") and the task are never summarised. A summary can paraphrase a rule into something weaker; pinning prevents that.

**Invariants.** (1) A token budget per call. (2) A fixed priority order: pinned > tools index > summary + recent > documents. (3) Every assembly is observable (the report).

**Lineage.** Virtual memory and paging (working set in RAM, the rest on disk); cache eviction policies; lazy loading in UIs. The running summary is a lossy log compaction.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| Conversations or agent loops run for many turns. | Calls are single-turn and small. |
| Tool catalogs or reference material exceed what one call should carry. | Everything relevant fits comfortably, with headroom. |
| Cost per call matters at volume. | You cannot tolerate any lossy summarisation (legal transcripts); keep full logs and retrieve instead. |
| Quality drops as context grows (lost-in-the-middle effects). | The extra summarizer calls cost more than the tokens they save. |

**Cheaper alternative:** a sliding window, keeping the last *N* turns and dropping the rest. It is fine until a dropped turn contained the one fact you needed (the ticket id). Upgrade when that happens, or when tool and document context crowds out the conversation.

## Forces & trade-offs

| Force | vs. send-everything | Why |
|---|---|---|
| Latency | ↓ | Shorter prompts are faster; occasional summarizer calls add a little. |
| Cost | ↓↓ at volume | 924 → 190 tokens in the example; summarizer calls are small-model calls. |
| Reliability | ↑ (less noise), with a new risk | Lossy summaries can drop facts; pinning and id-preservation mitigate. |
| Complexity | ↑ | Budget, priorities, summarizer prompt, eviction policy, reporting. |

## Trade-off analysis & usage guidance

**Model.** For a session of *T* turns, keep-recent *k*, summary size *S* and turn size *t*: managed prompt ≈ pinned + index + *S* + *k·t* + docs, which is roughly constant in *T*. Send-everything ≈ pinned + full tools + *T·t* + all docs, which is linear in *T*. Summarizer calls ≈ *T / k* with incremental updates.

**Decision checklist.**

1. What must *never* leave the context? Pin it.
2. Which identifiers (tickets, ids, amounts) must survive summarisation verbatim? (Exercise.)
3. Can tools and documents be disclosed lazily?
4. What is the relevance floor, and how is relevance scored?
5. What happens when the pinned parts alone exceed the budget? (`over_budget` must be surfaced, not hidden.)

**Usage in production.**

- Log the report for every call. Section sizes over time show what is crowding the window.
- Use a small, cheap model for compaction, with a strict "keep decisions, facts, ids, open items" prompt.
- Keep compaction incremental: summarise only turns not yet folded in.
- Re-check budgets when switching models; tokenisers differ.

## Worked example

### Example first: what happens

An on-call session: incident INC-4411, a bad deploy, a Friday, and a change ticket. Six tools with long docs and three reference documents. The budget is 300 tokens.

```
python3 code/patterns/context_management/main.py
```

<!-- expected-output: code/patterns/context_management/main.py -->
```text
Context management
==================
-- call 1: nothing loaded yet
[naive prompt] 924 tokens
[managed prompt] 190 tokens (budget 300): system=20, task=12, tools=77, summary=29, recent=31, docs=21
[compacted] 5 old turns → 1 summary (1 summarizer call)
[evicted] postmortem-2025 (relevance 0.40), style-guide (relevance 0.10)
-- call 2: the model asked help(deploy); two more turns happened
[managed prompt] 285 tokens: system=20, task=12, tools=187, summary=29, recent=16, docs=21
[evicted] postmortem-2025 (relevance 0.40), style-guide (relevance 0.10)
[progressive disclosure] full docs loaded for ['deploy']; other 5 tools stay one-liners
[compacted] 7 turns folded in total; summarizer calls=2 (incremental)
[pinned + recalled] rule present=True, CHG-881 present=True, INC-4411 present=True
```

**Call 1:** the naive prompt is 924 tokens; the managed prompt is 190. Five old turns become one summary, and the two irrelevant documents are evicted by the relevance floor. **Call 2:** the model asked for `help(deploy)`, so only that tool's full docs are loaded (tools: 77 → 187 tokens), and the total is still within budget at 285. Compaction is *incremental*: the summarizer folds in only the two turns that aged out. Throughout, the Friday rule is pinned and both ticket ids are present.

### Why first: why it is built this way

- **Sections are assembled in priority order, and documents fill what is left.** The budget is enforced where it is cheapest to give things up.
- **The relevance floor comes before the budget check.** A low-relevance document is noise even when it fits.
- **`over_budget` is reported, not silently fixed.** If the pinned parts alone exceed the budget, that is a design problem (rules too long, task too verbose). Truncating pinned content would be worse.
- **`loop_render` adapts the manager to the [tool-use loop (#9)](../part-2-single-agent/09-tool-use-loop.md).** The coding-team capstone plugs it in, and the loop does not change.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Lossy summary drops a key id | Agent re-asks, or acts without it. | Extract and pin ids before summarising (exercise). |
| Rule paraphrased away | "Never on Fridays" becomes "be careful on Fridays". | Pin rules; never summarise them. |
| Summary drift | Repeated re-summarising distorts facts. | Incremental summaries; keep original turns in a log for retrieval. |
| Thrashing tool docs | Model keeps requesting docs it was just shown. | Keep loaded docs for several turns; cap disclosures. |
| Silent truncation | Prompt cut mid-section by the API. | Assemble under your own budget with headroom; report `over_budget`. |
| Relevance mis-scoring | The needed runbook is evicted. | Calibrate scoring on real sessions; log evictions. |

## Variations

- **Retrieval-backed history.** Store all turns, and retrieve old ones by relevance instead of summarising.
- **Hierarchical summaries.** Summaries of summaries for very long sessions.
- **Sub-agent offloading.** Push a large sub-task into a fresh agent with its own clean context, and keep only its result. This is the context argument for [hierarchical teams (#13)](../part-3-multi-agent/13-hierarchical-teams.md).
- **Prompt caching awareness.** Keep pinned prefixes byte-stable so provider-side caching can reuse them.

## Try it

Summaries are lossy. A cheaper summarizer drops the incident id `INC-4411`, so the agent can no longer reference the incident. Make identifiers survive compaction **verbatim**: extract ticket-style ids from turns before they are summarised, and keep them in a pinned line of the summary.

→ Solution: [Solutions — Context management](../solutions/20-context-management.md)

## 60-second interview lens

- **Say:** "Context management assembles each call's context under a token budget: pin rules and the task, disclose tool docs on demand, compact old turns into a running summary, and fill the rest with the most relevant documents, logging every decision."
- **Trade-off to name:** big savings in cost and noise, against lossy summaries, so pin rules and identifiers and keep the full log retrievable.
- **Expect the follow-up:** "How is this different from memory?" Memory decides what persists across time; context management decides what goes into this one call.
- **Red flag to avoid:** letting the provider truncate silently, or summarising the rules.

## Related patterns

- [Memory tiers (#19)](19-memory-tiers.md): persistence across calls and sessions.
- [Tool-use loop (#9)](../part-2-single-agent/09-tool-use-loop.md): the runtime whose transcript this pattern keeps in budget.
- [Hierarchical teams (#13)](../part-3-multi-agent/13-hierarchical-teams.md): context scoping by splitting agents.
- [Coding-team capstone](../capstones/coding-team.md): every developer prompt ≤ 300 tokens.
