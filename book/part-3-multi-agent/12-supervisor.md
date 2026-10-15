# 12. Supervisor

> **Intent.** Put one coordinating agent in charge of a set of specialist agents: it delegates one instruction at a time, reads every result, and decides again — another specialist, a retry with new instructions, or finish.

**Also known as:** coordinator, manager agent, hub-and-spoke multi-agent · **Part:** 3 — Multi-agent coordination · **Code:** `code/patterns/supervisor/`

## Structure

![Supervisor structure](../diagrams/supervisor.svg)

The supervisor model sees the task, the roster of workers with one-line descriptions, and the history of results. It returns `{"next", "instruction"}` or `{"next": "FINISH", "final"}`. Code validates the worker name, refuses an exact repeat of an earlier delegation (loop guard), runs the worker, and appends the result. A turn budget bounds the whole run.

## Design concept & theory

**Core idea.** A [router (#2)](../part-1-workflow/02-routing.md) decides once and leaves. A supervisor stays: after each worker's turn it re-reads the situation and decides again. That makes it the simplest multi-agent pattern that can *notice a gap and send work back*.

**Why it works.**

- *Separation of judgement from execution.* Workers are narrow and good at one thing. The supervisor does none of the work; it judges progress against the goal. Narrow workers with a judging coordinator are easier to prompt, test and swap than one agent that does everything.
- *Closed-loop control.* Each decision is conditioned on actual results, not on a plan written before anything happened. In the example the writer's first draft lacks numbers, the supervisor sees that, and it sends the analyst in. A fixed pipeline would have shipped the vague draft.
- *Single point of authority.* Exactly one agent decides what happens next, so there are no conflicting instructions and no deadlocks between peers. The cost is that the supervisor is a bottleneck and a single point of failure, which is why its decisions are validated in code.
- *Cost grows with turns × history.* Every decision re-reads the history, so supervisor prompt tokens grow roughly quadratically in turns unless worker outputs are kept short (the exercise).

**Invariants.** (1) One supervisor; workers never talk to each other directly. (2) The supervisor re-decides after every worker turn. (3) Code owns validation, loop detection and the turn budget.

**Lineage.** The *Mediator* pattern (colleagues communicate only through the mediator); a scheduler with a work queue; a human team lead doing stand-ups.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The order of specialist work depends on intermediate results. | The order is fixed: use a [chain (#1)](../part-1-workflow/01-prompt-chaining.md). |
| Work may need to be sent back ("redraft with numbers"). | One decision suffices: use a [router (#2)](../part-1-workflow/02-routing.md). |
| Specialists have meaningfully different prompts or tools. | "Specialists" are the same model with cosmetic role names. |
| You need one place to enforce budgets and stop conditions. | More than ~6 workers or deep sub-structure: use [hierarchical teams (#13)](13-hierarchical-teams.md). |

**Cheaper alternative:** a [prompt chain](../part-1-workflow/01-prompt-chaining.md) with a code gate that loops back one step when the gate fails. Upgrade to a supervisor when the *choice* of who works next genuinely needs judgement.

## Forces & trade-offs

| Force | vs. a fixed chain | Why |
|---|---|---|
| Latency | ↑ | One supervisor call between every worker call. |
| Cost | ↑ | Supervisor calls re-read growing history. |
| Reliability | ↑ on variable tasks | Gaps are noticed and fixed; a bad supervisor decision is a new failure mode. |
| Complexity | ↑ | Roster, decision schema, validation, loop guard, budget. |

## Trade-off analysis & usage guidance

**Model.** With *w* worker turns, supervisor calls = *w + 1* (the last one says FINISH). In the example: 4 worker turns, 5 supervisor calls. Supervisor prompt tokens ≈ Σ over turns of (roster + history so far), roughly *w²/2 × average result size*. That is why the exercise clips history entries: 1,446 → 523 prompt tokens with no change in behaviour.

**Decision checklist.**

1. Is there a real decision between worker turns, or is the order fixed?
2. Are worker outputs short, or summarised before the supervisor sees them?
3. What is the turn budget, and what does the user get when it is spent?
4. How is "done" defined? Is it in the supervisor's prompt, and checkable by code where possible?
5. Can a worker failure be represented as a result the supervisor can act on?

**Usage in production.**

- Log every decision with the history length at that point. Supervisor quality problems show up as long, repetitive histories.
- Keep worker outputs concise and put full artefacts in shared state, not in the supervisor's prompt.
- Make the roster descriptions precise. The supervisor can only delegate well to workers it understands.
- Alert on budget exhaustion; it usually means a missing worker or an impossible task.

## Worked example

### Example first: what happens

```
python3 code/patterns/supervisor/main.py
```

<!-- expected-output: code/patterns/supervisor/main.py -->
```text
Supervisor
==========
-- Write a one-sentence pricing brief
[supervisor → researcher] Collect competitor list prices
[researcher] Monthly list prices: Acme (us) $49, Beta $59, Gamma $45
[supervisor → writer] Draft one sentence positioning our price
[writer] Acme sits between Beta and Gamma on price.
[supervisor → analyst] Compute our price difference vs each competitor in %
[analyst] Acme vs competitors: -17% vs Beta, +9% vs Gamma
[supervisor → writer] Redraft using the percentage comparison
[writer] Acme is priced mid-market: 17% below Beta and 9% above Gamma.
[supervisor] FINISH: Acme is priced mid-market: 17% below Beta and 9% above Gamma.
result: finished after 4 worker turns, 5 supervisor calls
-- Same task, a supervisor that repeats itself
[supervisor → researcher] Collect competitor list prices
[researcher] Monthly list prices: Acme (us) $49, Beta $59, Gamma $45
[supervisor] STOP — loop: researcher already did 'Collect competitor list prices'
result: ok=False, loop: researcher already did 'Collect competitor list prices'
```

The supervisor gets prices, then asks for a draft. The first draft, "Acme sits between Beta and Gamma on price", is vague, and the supervisor's next decision reacts to that by sending the analyst to compute percentages, then the writer to redraft. Then it finishes. Nobody planned the analyst step in advance; it was decided from what the draft lacked.

The second run shows a supervisor that keeps asking the researcher for the same thing. Code detects the exact repeat and stops after one turn instead of burning the budget.

### Why first: why it is built this way

- **Workers are plain callables `(instruction, state) -> str`.** A worker can be an agent, a chain, a tool or a whole team, which is exactly how [hierarchical teams (#13)](13-hierarchical-teams.md) reuses this class.
- **Shared `state` carries artefacts; the history carries summaries.** The analyst reads prices from `state`, not from the supervisor's prompt. Keeping data out of the coordinator's context is what keeps the coordinator cheap.
- **The loop guard compares (worker, instruction).** An exact repeat is a strong "stuck" signal. A *different* instruction to the same worker (redraft with numbers) is allowed, because that is the pattern working.
- **Unknown worker names stop the run.** A supervisor that invents a worker is misconfigured; failing loudly beats guessing.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Ping-pong | Same worker, same instruction, repeatedly. | Exact-repeat guard; turn budget. |
| Premature FINISH | Ends before the task is complete. | Explicit done criteria; code checks on the final artefact. |
| Never finishes | Keeps polishing. | Turn budget; "is this good enough?" criterion in the prompt. |
| Context bloat | Supervisor prompt grows with each verbose result. | Clip or summarise history (exercise); artefacts in state. |
| Doing the work itself | Supervisor writes the answer instead of delegating. | Instruction "delegate; do not do the work"; FINISH only with worker-produced output. |
| Invented workers | Delegates to a name not in the roster. | Validate names; stop or re-ask. |

## Variations

- **Supervisor with tools.** The supervisor can also call cheap tools directly (look up status) without delegating.
- **Parallel delegation.** The supervisor issues several independent instructions per turn and gets results back together ([#3](../part-1-workflow/03-parallelization.md)).
- **Plan-guided supervisor.** The supervisor first writes a plan ([#7](../part-2-single-agent/07-plan-and-execute.md)), then delegates against it, re-planning on surprises.
- **Supervisor of teams.** Workers are themselves supervisors: [hierarchical teams (#13)](13-hierarchical-teams.md).

## Try it

The supervisor re-reads every worker's full output on every turn. Clip each history entry to a fixed number of characters (workers keep full results in shared state) and show the run still finishes with far fewer supervisor prompt tokens, *without changing `Supervisor.run()`*.

→ Solution: [Solutions — Supervisor](../solutions/12-supervisor.md)

## 60-second interview lens

- **Say:** "A supervisor is a coordinating agent that delegates one instruction at a time to specialists, reads every result and decides again, so it can notice gaps and send work back."
- **Trade-off to name:** you gain adaptivity, and you pay a coordination call per turn on a growing history, with a single point of failure.
- **Expect the follow-up:** "Supervisor or router?" A router decides once and exits; a supervisor stays in the loop. Use a router unless results need to change who works next.
- **Red flag to avoid:** no turn budget or loop detection, because "the supervisor will know when to stop".

## Related patterns

- [Routing (#2)](../part-1-workflow/02-routing.md): one decision, then exit.
- [Orchestrator–workers (#4)](../part-1-workflow/04-orchestrator-workers.md): one planning pass over stateless workers; no turn-by-turn re-decision.
- [Hierarchical teams (#13)](13-hierarchical-teams.md): supervisors of supervisors.
- [Coding-team capstone](../capstones/coding-team.md): this class as the tech lead and both team leads.
