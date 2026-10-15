# Agentic Design Patterns — Scope Sheet (Gate 1: Inventory Lock)

Status: **DRAFT — awaiting approval.** No chapters or code are written until this sheet is approved.
Pattern list is exactly as specified (21 patterns, 4 parts). No additions, cuts, or renames are proposed.

## How to read the boundaries

Each pattern gets one line: **what it is**, then **"Not:"** naming the neighbouring pattern it is most often confused with and the dividing line. The dividing lines are summarised in the overlap matrix at the end.

Two axes keep the catalog orthogonal:

- **Who decides control flow?** Code (Part 1 workflows) → one model (Part 2) → several models (Part 3).
- **Is it a structure or a concern?** Parts 1–3 are structures; Part 4 patterns are concerns that apply to any structure.

---

## Part 1 — Workflow patterns (control flow fixed in code)

| # | Pattern | Slug | One-line boundary |
|---|---------|------|-------------------|
| 1 | Prompt chaining | `prompt_chaining` | A fixed, linear sequence of LLM calls where each step's output is the next step's input, with optional code "gates" between steps. **Not:** sequential handoffs (#14) — chain steps are stateless calls owned by one program, not autonomous agents transferring ownership of a conversation. |
| 2 | Routing | `routing` | Classify an input once, then dispatch it to exactly one specialised downstream path. **Not:** supervisor (#12) — a router decides once and exits; a supervisor stays in the loop and re-decides after every worker turn. |
| 3 | Parallelization (fan-out/fan-in) | `parallelization` | Run N independent LLM calls concurrently on a statically known split (sectioning) or on the same input (voting), then aggregate in code. **Not:** orchestrator–workers (#4) — the subtasks are known before runtime; nothing is decomposed by a model. |
| 4 | Orchestrator–workers | `orchestrator_workers` | An LLM decomposes a task into subtasks at runtime, dispatches them to worker calls, and synthesises the results — in a single pass. **Not:** supervisor (#12) — workers are stateless function calls and there is no ongoing multi-turn delegation; **not** plan-and-execute (#7) — no re-planning on observed results. |
| 5 | Evaluator–optimizer | `evaluator_optimizer` | A generator call and a *separate* evaluator call (prompted with an explicit rubric) loop until the evaluator passes or a budget runs out. **Not:** reflection (#8) — the evaluator is a distinct role with its own rubric, not the generator critiquing itself; **not** guardrailed generation (#11) — the check is a judgement of quality, not a deterministic validity test. |

## Part 2 — Single-agent reasoning (one model drives control flow)

| # | Pattern | Slug | One-line boundary |
|---|---------|------|-------------------|
| 6 | ReAct | `react` | Interleave explicit *Thought → Action → Observation* steps in one growing trace, so reasoning is grounded in each observation before the next action. **Not:** tool-use loop (#9) — ReAct is about the *reasoning trace* format and its interpretability; the tool-use loop is the *runtime mechanics* (schemas, dispatch, errors, stop conditions) that any agent needs, with or without visible thoughts. |
| 7 | Plan-and-execute (with re-planning) | `plan_and_execute` | Produce an explicit multi-step plan up front, execute steps (often with a cheaper executor), and re-plan when observations invalidate the remaining plan. **Not:** ReAct (#6) — the plan is a first-class artefact decided before acting, not decided one step at a time; **not** orchestrator–workers (#4) — it revisits the plan. |
| 8 | Reflection / self-critique | `reflection` | The same agent reviews its own output (or trajectory), writes a critique, and revises — no external judge. **Not:** evaluator–optimizer (#5) or critic–reviewer (#16) — those use a separate evaluator role; reflection is cheap, introspective, and shares the generator's blind spots. |
| 9 | Tool-use loop | `tool_use_loop` | The canonical agent runtime: model emits a structured tool call → host validates and executes it → result is appended → repeat until the model emits a final answer or a step/cost limit trips. **Not:** ReAct (#6) — see above; this chapter owns tool schemas, error results, retries, and termination. |
| 10 | Agentic RAG | `agentic_rag` | The agent decides *whether, what, and where* to retrieve, judges relevance of what came back, and re-queries until evidence suffices — retrieval as a tool inside the loop. **Not:** classic RAG (retrieve-once-then-generate, the cheaper alternative); **not** memory tiers (#19) — RAG reads an external corpus the agent doesn't own; memory is the agent's own written history. |
| 11 | Guardrailed generation | `guardrailed_generation` | Generate → validate with deterministic checks (schema, policy, PII, citations) → repair with targeted error feedback, with a hard retry cap and safe fallback. **Not:** evaluator–optimizer (#5) — validators are code with pass/fail semantics, not an LLM's quality opinion. *(Canonical module, built early for Capstone 2.)* |

## Part 3 — Multi-agent coordination (several models, explicit roles)

| # | Pattern | Slug | One-line boundary |
|---|---------|------|-------------------|
| 12 | Supervisor | `supervisor` | One coordinating agent repeatedly chooses which specialist agent acts next, sees each result, and decides when the job is done (hub-and-spoke, multi-turn). **Not:** routing (#2) — it never exits after one decision; **not** hierarchical teams (#13) — exactly one level. |
| 13 | Hierarchical teams | `hierarchical_teams` | Supervisors of supervisors: a top-level lead delegates to team leads, each running its own sub-team, with summaries flowing up. **Not:** supervisor (#12) — the defining feature is ≥2 levels with scoped context per team. |
| 14 | Sequential handoffs | `sequential_handoffs` | Agents transfer *ownership* of a live task/conversation to the next agent via an explicit handoff object (state + reason), with no central coordinator. **Not:** prompt chaining (#1) — participants are agents with their own tools and instructions, and the handoff target can be chosen at runtime. |
| 15 | Debate / peer critique | `debate` | Two or more *peer* agents argue positions over rounds and a judge (or vote) resolves — used to surface disagreement and reduce single-model bias. **Not:** critic–reviewer (#16) — peers are symmetric and each can be right; there is no fixed author/reviewer hierarchy. |
| 16 | Critic–reviewer loop | `critic_reviewer` | An *author* agent produces an artefact and a *reviewer* agent with different instructions/tools (e.g. can run tests) returns structured findings until approval. **Not:** evaluator–optimizer (#5) — both sides are full agents that can act with tools across turns, and findings are itemised review comments, not a score; **not** debate (#15) — roles are asymmetric. |
| 17 | Human-in-the-loop | `human_in_the_loop` | Pause execution at defined checkpoints (approve, edit, reject, answer) based on risk/confidence policy, persist state, and resume deterministically. **Not:** guardrailed generation (#11) — a human, not code, is the validator, and the system must survive waiting. *(Canonical module, built early for Capstone 2.)* |
| 18 | Swarm | `swarm` | Many peer agents with no central controller coordinate through local rules, shared state (blackboard), or peer handoffs; behaviour emerges. Chapter includes an honest **"when not to use"** section (usually: don't). **Not:** parallelization (#3) — agents interact and the workload is not fixed in advance; **not** sequential handoffs (#14) — many concurrent agents, not one owner at a time. |

## Part 4 — Cross-cutting concerns (apply to any structure)

| # | Pattern | Slug | One-line boundary |
|---|---------|------|-------------------|
| 19 | Memory tiers | `memory_tiers` | Separate what the agent remembers by lifetime and access: working (in-context), short-term (session/episodic), long-term (semantic/procedural store) with explicit write, consolidate, and recall policies. **Not:** context management (#20) — memory is about *what is stored across time*; context management is about *what fits in this one call*. **Not:** agentic RAG (#10) — see above. |
| 20 | Context management | `context_management` | Budget the context window per call: progressive disclosure (load detail only when needed), compaction (summarise old turns), pinning, and eviction. **Not:** memory tiers (#19) — compaction may write to memory, but this chapter owns the per-call token budget. |
| 21 | Eval harness | `eval_harness` | Fixed datasets + deterministic scorers + (optional) LLM-judge scorers + regression reports, run offline against any pattern to decide whether a change is better. **Not:** evaluator–optimizer (#5) — that's a *runtime* loop improving one output; the harness is *development-time* measurement across many cases. *(Canonical module, built early for Capstone 2.)* |

---

## Overlap matrix — the distinctions the book will hold firm

| Confusable cluster | Dividing question | Answer → pattern |
|---|---|---|
| Evaluator–optimizer / Reflection / Critic–reviewer / Debate / Guardrailed generation | Who judges, and how? | Code → **#11** · same model → **#8** · separate rubric-driven call → **#5** · separate tool-using agent with itemised findings → **#16** · symmetric peers + judge → **#15** |
| Routing / Supervisor | How many decisions? | One, then exit → **#2** · repeated, stays in loop → **#12** |
| Parallelization / Orchestrator–workers / Swarm | Who splits the work? | Code, statically → **#3** · an LLM, once → **#4** · nobody centrally, emergent → **#18** |
| Orchestrator–workers / Supervisor / Hierarchical / Plan-and-execute | Single pass vs. ongoing; levels; re-planning? | One pass, stateless workers → **#4** · ongoing, one level → **#12** · ≥2 levels → **#13** · single agent with re-planning → **#7** |
| Prompt chaining / Sequential handoffs | Calls or agents? | Fixed calls in code → **#1** · agents transferring ownership → **#14** |
| ReAct / Tool-use loop | Reasoning format or runtime mechanics? | Visible thought trace → **#6** · dispatch, validation, termination → **#9** |
| Agentic RAG / Memory tiers / Context management | External corpus, own history, or this call's window? | **#10** · **#19** · **#20** |
| Evaluator–optimizer / Eval harness | Runtime or development-time? | **#5** · **#21** |

---

## Standard chapter template (proposed; locked only after pilot approval)

1. **Intent** — one sentence.
2. **When to use / when not to use** — names the cheaper alternative explicitly.
3. **Forces & trade-offs** — table rating latency, cost, reliability, complexity (vs. the cheaper alternative).
4. **Diagram** — hand-placed inline SVG, warm palette, editable source in `book/diagrams/<slug>.svg`. No Mermaid.
5. **Worked example** — (a) example-first walkthrough of the companion code's actual run; (b) why-first explanation of the design.
6. **Failure modes & guardrails** — table: symptom → cause → guardrail.
7. **Variations**.
8. **Try it** — exercise; solution lives in the separate Solutions appendix (`book/solutions/<slug>.md`).
9. **60-second interview lens** — what to say, the trade-off to name, the follow-up question to expect.
10. *Footer:* run command, expected output, related patterns (cross-links).

## Companion code layout (proposed)

```
code/
  agentkit/                 # tiny shared stdlib-only kernel: MockLLM (scripted, deterministic), mock tools, tracing
  patterns/<slug>/          # one runnable example per pattern: main.py + README (run command + expected output)
  capstones/
    deep_research/          # brief.md + solution
    support_triage/
    coding_team/
  verify.py                 # runs all 21 patterns + 3 capstones, checks expected output, exits non-zero on any failure
book/
  00-scope-sheet.md, part-1/..., solutions/..., diagrams/...
dist/
  agentic-design-patterns.html, agentic-design-patterns.md
```

- Python standard library only; no network, no credentials.
- **No duplicate implementations:** canonical modules for #11, #17, #21 live in `code/patterns/<slug>/` and are *imported* by capstones; each capstone imports pattern modules rather than re-implementing them.
- Each example asserts its own expected result; `python3 code/verify.py` is the single green/red gate.

## Capstone → pattern ownership

| Capstone | Patterns composed | Built in phase |
|---|---|---|
| Support triage (pilot) | #2 Routing, #3 Parallelization, #11 Guardrailed generation, #17 HITL, #21 Eval harness | 2 (pilot) |
| Deep-research agent | #7 Plan-and-execute, #10 Agentic RAG, #8 Reflection, #5 Evaluator–optimizer, #19 Memory tiers | 3 |
| Multi-agent coding team | #12 Supervisor, #13 Hierarchical teams, #16 Critic–reviewer, #9 Tool-use loop, #20 Context management | 3 |

## Phase plan

1. **Gate 1 (now):** approve this sheet.
2. **Gate 2 — Pilot:** Part 1 chapters (#1–#5) + template + `agentkit` + canonical #11/#17/#21 code modules + Support-triage capstone, verified green.
3. **Gate 3 — Full build**, in tranches, each verified before presentation: (a) Part 2 + Deep-research capstone; (b) Part 3 + Coding-team capstone; (c) Part 4 chapters.
4. **Gate 4 — Assembly:** single warm-themed, responsive, print-ready HTML + combined Markdown, page-count estimate.

## Open questions for you

1. Slugs above OK (they become folder names and anchor IDs)?
2. Python version floor — I'll target **3.10+** unless you say otherwise.
3. Working branch — commit to a feature branch (e.g. `book/agentic-design-patterns`) and push, or keep `main`?
