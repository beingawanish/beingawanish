# 4. Orchestrator–workers

> **Intent.** Let a model decompose a task into subtasks *at runtime*, run each subtask with a focused worker call, and merge the results with one synthesis call — in a single pass.

**Also known as:** dynamic decomposition, planner–workers, master–worker · **Part:** 1 — Workflow · **Code:** `code/patterns/orchestrator_workers/`

## Structure

![Orchestrator–workers structure](../diagrams/orchestrator_workers.svg)

The orchestrator (a model) writes a plan: a list of subtasks, each naming the source it needs. Code validates the plan (size cap, known sources) before anything runs. Workers execute concurrently, each seeing only its own subtask and source. The orchestrator then synthesises the outputs. There is one plan and one synthesis, with no loop back.

## Design concept & theory

**Core idea.** This is [parallelization (#3)](03-parallelization.md) for the case where you cannot write the split in advance. How many files does this change touch? Which documents matter for this question? Only the input can say, so a model reads the input and decides the fan-out.

**Why it works.**

- *Decomposition is a skill models are good at.* Listing the parts of a task is usually much easier than doing all the parts at once. The orchestrator does the cheap, global part (what needs doing); workers do the expensive, local parts (doing it).
- *Context isolation.* Each worker sees one subtask and one source, not the whole task. Smaller, focused contexts mean less distraction and cheaper calls, and the possibility of using a smaller model for workers. Total tokens can even *fall*, because no single call has to hold everything.
- *Separation of planning from execution makes both auditable.* The plan is an inspectable artefact (JSON) *before* any work is done. You can validate it, cap it, log it, and reject it, as the third run in the example does.

**Invariants.** (1) A model decides the subtasks at runtime. (2) Workers are stateless calls that do not talk to each other. (3) Single pass: plan, execute, synthesise. If the plan is revised based on what workers return, you have [plan-and-execute (#7)](../part-2-single-agent/07-plan-and-execute.md). If the coordinator keeps delegating turn by turn to stateful agents, you have a [supervisor (#12)](../part-3-multi-agent/12-supervisor.md).

**Lineage.** *Master–worker* (task farm) from parallel computing; the *Process Manager* and *Splitter → Aggregator* pair from Enterprise Integration Patterns, with the routing slip computed dynamically.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The number or kind of subtasks depends on the input (files in a diff, sources for a question). | You can write the split in code (use [parallelization, #3](03-parallelization.md)). |
| Subtasks are independent once identified. | Subtask *k* needs subtask *k−1*'s result (use a chain or [plan-and-execute, #7](../part-2-single-agent/07-plan-and-execute.md)). |
| The whole input is too large or too distracting for one call. | The task is small enough that one call handles it well. |
| You want a reviewable plan before spending on execution. | Failures discovered during execution should change the plan (that needs re-planning). |

**Cheaper alternative:** a fixed fan-out over an obvious unit (one worker per file, always), which is parallelization with a code-computed split. Upgrade when the obvious unit is wrong: some files need no work, some need two kinds of work, and some subtasks span several files.

## Forces & trade-offs

| Force | vs. fixed fan-out | Why |
|---|---|---|
| Latency | ↑ | Plan and synthesis are two extra sequential calls around the parallel phase. |
| Cost | ≈ | Extra orchestrator calls, offset by skipping unnecessary workers and using small worker models. |
| Reliability | ↑ when the split matters, with a new risk | Better decomposition, but the plan itself can be wrong (missing, extra or hallucinated subtasks). |
| Complexity | ↑ | Plan schema, plan validation, worker isolation, synthesis prompt. |

## Trade-off analysis & usage guidance

**Model.** With plan cost *c_p*, *N* workers at *c_w*, and synthesis *c_s*:

- Cost = *c_p + N·c_w + c_s*. Workers on a small model often make *N·c_w* the smallest term. The example's worker is priced at a tenth of the orchestrator's.
- Latency ≈ *t_p + max(t_w) + t_s*: three sequential phases, the middle one parallel.
- Cap *N*. Without a cap, cost is unbounded and set by the model's enthusiasm for decomposition.

**Decision checklist.**

1. Would a human need to *read the input* to know how to split the work?
2. Once split, are the pieces independent?
3. Can you write a plan schema and validate it (size, allowed sources and tools)?
4. Is one pass enough, or will workers' findings need to reshape the plan?
5. Can workers run on a cheaper model?

**Usage in production.**

- Validate the plan *as untrusted input*: schema, maximum subtasks, allowed sources, no duplicates. The plan is model output, and it decides what your system touches.
- Log the plan separately from the result. Most quality issues trace to the plan, not the workers.
- Pass workers the minimum context they need. Isolation is a feature.
- Make the synthesis prompt cite subtask IDs, so the result is traceable to the worker that produced each claim.

## Worked example

### Example first: what happens

The same orchestrator receives three tasks over a small code repository:

```
python3 code/patterns/orchestrator_workers/main.py
```

<!-- expected-output: code/patterns/orchestrator_workers/main.py -->
```text
Orchestrator-workers
====================
-- Write the PR description for the auth hardening change
[plan] 3 subtask(s): login, session, docs
[worker:login] Adds rate limiting: 5 failed attempts per 15 minutes.
[worker:session] Session lifetime reduced from 24h to 8h.
[worker:docs] Docs say 8 hours — consistent with the code.
[synthesize] Security hardening: login is rate-limited (5 tries / 15 min) and sessions now last 8h instead of 24h. Docs updated and consistent.
-- Write a customer note about the auth change
[plan] 1 subtask(s): session
[worker:session] Users are signed out after 8h instead of 24h.
[synthesize] Heads-up: for your security you'll now be asked to sign in again after 8 hours.
-- Audit everything touching customer data
[plan] REJECTED — plan references unknown sources ['db/prod.sql']
orchestrator: 5 calls; workers: 4 calls
```

- **PR description:** the orchestrator plans three subtasks (two code files and the docs). It ignores `billing/invoice.py`, which is unchanged. Three workers run concurrently, and the synthesis merges them.
- **Customer note:** the same repository and a different task give a *different plan*, one subtask focused on user impact. A fixed fan-out over files would have run four workers here.
- **Audit:** the orchestrator proposes reading `db/prod.sql`, which is not an allowed source. Plan validation rejects it before any worker runs, at the cost of one call.

The final line, *5 orchestrator calls and 4 worker calls*, is the whole cost of three tasks, and the worker calls are the cheap ones.

### Why first: why it is built this way

- **The plan is JSON, and it is validated.** `plan()` checks shape, size and sources. Free-text plans cannot be capped or audited, and an unchecked plan lets the model choose what your system reads.
- **Workers reuse `fan_out`.** Concurrency, error capture and stable ordering come from [parallelization (#3)](03-parallelization.md). The orchestrator only adds planning and synthesis.
- **A failed worker is visible in the synthesis.** A worker error becomes `[worker failed: …]` in the synthesis input, so the final answer can say what is missing instead of silently omitting it. The exercise adds a retry without touching `orchestrate()`.
- **Same model for planning and synthesis.** Both are global, judgement-heavy steps that need the whole task in view. Workers do local, mechanical work and use the cheap model.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Hallucinated subtask | Plan references a file, tool or source that does not exist or is not allowed. | Validate the plan against an allow-list; reject or re-plan once. |
| Over-decomposition | Ten tiny subtasks; cost and synthesis quality suffer. | Hard cap; prompt for "at most N, merge small items"; track N per task type. |
| Missed subtask | The plan omits something needed; synthesis is confidently incomplete. | Coverage check in code where possible (every changed file is in some subtask). |
| Inconsistent workers | Workers contradict each other; synthesis blends them. | Have workers return structured fields; let the synthesis flag conflicts rather than average them. |
| Synthesis hallucination | Final answer contains claims no worker produced. | Require citations to subtask IDs; spot-check with an [eval harness (#21)](../part-4-cross-cutting/21-eval-harness.md) scorer. |
| Lost failure | A worker failed; the answer does not say so. | Pass failures into synthesis explicitly; mark the result partial. |

## Variations

- **Typed workers.** The plan assigns each subtask a worker *type* (summariser, test-writer, translator), each with its own prompt. This is a router per subtask.
- **Coverage-checked plan.** Code computes the units that must be covered (changed files, required sections) and rejects plans that miss any.
- **Two-level decomposition.** A worker may itself orchestrate. Stop at two levels; beyond that, see [hierarchical teams (#13)](../part-3-multi-agent/13-hierarchical-teams.md).
- **Map-reduce synthesis.** With many workers, synthesise in a tree (pairs, then pairs of pairs) to keep each synthesis context small.

## Try it

One worker call times out on its first attempt. Today the synthesis receives `[worker failed: …]`. Make workers retry once on transient errors **without changing `orchestrate()`**, then show that the synthesis receives all three results and that exactly one retry happened. (Hint: what single interface do all patterns depend on?)

→ Solution: [Solutions — Orchestrator–workers](../solutions/04-orchestrator-workers.md)

## 60-second interview lens

- **Say:** "Orchestrator–workers is dynamic fan-out: a model reads the task and decides the subtasks, workers do them in parallel with isolated context, and one call synthesises, all in a single pass."
- **Trade-off to name:** you gain a decomposition fitted to the input, and you add a new failure surface, the plan, which must be validated like untrusted input.
- **Expect the follow-up:** "How is this different from a supervisor agent?" One pass, stateless workers, no turn-by-turn re-delegation. A supervisor stays in the loop and adapts.
- **Red flag to avoid:** letting the plan reference arbitrary tools or data without an allow-list.

## Related patterns

- [Parallelization (#3)](03-parallelization.md): same fan-out, but code fixes the split in advance.
- [Plan-and-execute (#7)](../part-2-single-agent/07-plan-and-execute.md): the plan is revised as results come in.
- [Supervisor (#12)](../part-3-multi-agent/12-supervisor.md): ongoing, multi-turn delegation to stateful agents.
- [Hierarchical teams (#13)](../part-3-multi-agent/13-hierarchical-teams.md): orchestration with two or more levels and scoped context per team.
