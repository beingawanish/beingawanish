# 13. Hierarchical teams

> **Intent.** Organise agents as supervisors of supervisors: a top lead delegates to team leads, each team works with its own private context and state, and only a short summary flows back up, so no single agent has to hold the whole job in its head.

**Also known as:** nested supervisors, multi-level delegation, team of teams · **Part:** 3 — Multi-agent coordination · **Code:** `code/patterns/hierarchical_teams/`

## Structure

![Hierarchical teams structure](../diagrams/hierarchical_teams.svg)

The launch lead delegates to two team leads. Each team lead is a full [supervisor (#12)](12-supervisor.md) over its own workers, with its own loop and private state. The top lead sends one instruction and receives one summary per team. Team-internal detail (interview notes, drafts, intermediate numbers) never leaves the team.

## Design concept & theory

**Core idea.** A flat supervisor's context grows with every worker it manages and every result they return. Hierarchy bounds that growth by *scoping*: each lead sees only its own level. It is the organisational chart, applied to context windows.

**Why it works.**

- *Context scoping.* The top lead's prompt contains two summaries, not four workers' raw output. In the example its largest prompt is 67 words against the flat supervisor's 237. Smaller contexts mean cheaper calls and less distraction for the agent making the highest-level decisions.
- *Encapsulation.* A team is a unit with an interface: one instruction in, one summary out. Teams can be developed, tested and replaced independently, and different teams can use different models.
- *Fault containment.* A failure inside a team can be handled inside the team (the exercise) and surfaced upward as a summary, rather than crashing the whole job.
- *The price is coordination.* Every level adds supervisor calls: 9 in the example against 5 for the flat version. Hierarchy trades *more* calls for *smaller* ones. It pays off when per-call context size is the binding constraint (quality degrades, or the window overflows), not when call count is.

**Invariants.** (1) Two or more levels of delegation. (2) Each team has private state and its own coordinator. (3) Only summaries cross level boundaries.

**Lineage.** The *Composite* pattern (a team is a worker); organisational hierarchy and span of control; layered architectures, where each layer talks only to its neighbours.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| A flat supervisor's context is too large or too noisy to decide well. | A flat supervisor with ≤ 5 workers works fine. Hierarchy is pure overhead there. |
| Work divides into teams with distinct expertise and little cross-talk. | Teams would need constant fine-grained exchange. |
| You want to develop, test or swap subsystems independently. | Latency budgets cannot absorb extra coordination calls. |
| Failures should be contained and summarised, not propagated. | Total call count is the binding cost. |

**Cheaper alternative:** a single [supervisor (#12)](12-supervisor.md) with clipped history (its exercise). Upgrade to hierarchy when, even with clipping, the coordinator has too many workers to choose between or too much detail to read.

## Forces & trade-offs

| Force | vs. a flat supervisor | Why |
|---|---|---|
| Latency | ↑ | Extra coordination calls at each level. |
| Cost | ↑ calls, ↓ tokens per call | More decisions, each over a smaller context. |
| Reliability | ↑ at scale | Focused leads decide better; failures are contained. |
| Complexity | ↑ | Team interfaces, summary contracts, multi-level debugging. |

## Trade-off analysis & usage guidance

**Model.** For *L* levels with fan-out *f* and *w* workers per team, coordination calls ≈ Σ over leads of (delegations + 1). The largest context at the top ≈ *f* × summary size, independent of *w*: that is the whole point. The example has 3 + 3 + 3 = 9 lead calls, a largest top-lead prompt of 67 words, and a largest team-lead prompt of 203 (research, with long interview notes); the flat version has 5 calls with a largest prompt of 237.

**Decision checklist.**

1. Is the flat coordinator's context actually a problem (quality, window, cost per call)?
2. Do the teams have natural boundaries with little cross-traffic?
3. What is each team's summary contract: what must it contain, and how long may it be?
4. How do team failures surface to the parent?
5. Is the depth ≤ 3? Every level adds latency and indirection.

**Usage in production.**

- Define summary contracts explicitly ("status, result, open questions, ≤ 60 words"). Summaries are the API between levels.
- Trace with level-aware ids (`launch/content/editor`) so a failure can be located in the tree.
- Budget per team, not just globally, so one team cannot starve the others.
- Prefer two levels; reach for three only with evidence.

## Worked example

### Example first: what happens

```
python3 code/patterns/hierarchical_teams/main.py
```

<!-- expected-output: code/patterns/hierarchical_teams/main.py -->
```text
Hierarchical teams
==================
-- hierarchical: launch_lead → {research_lead, content_lead} → 4 workers
[launch_lead → research_team] Establish demand for scheduled exports
[research_lead → market_researcher] Survey admins about exports
[market_researcher] Findings: 62% of surveyed admins export reports weekly. Interview note: customers export weekly rep…
[research_lead → data_analyst] Pull CSV export usage
[data_analyst] Usage data: 41% of active teams used CSV export last month; median 3 exports/week. Interview note:…
[research_lead] FINISH: Demand is real: 62% export weekly by hand; 41% of teams used CSV export last month.
[research_team] Demand is real: 62% export weekly by hand; 41% of teams used CSV export last month.
[launch_lead → content_team] Write the launch headline
[content_lead → writer] Draft the launch headline
[writer] Draft: Scheduled exports are here — set it once, get your report every Monday.
[content_lead → editor] Tighten the headline
[editor] Edited: Scheduled exports: set it once and your report arrives every Monday.
[content_lead] FINISH: Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
[content_team] Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
[launch_lead] FINISH: Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
-- flat: one supervisor over the same 4 workers
-- comparison (supervisor calls; largest supervisor prompt in words)
[launch_lead] 3 calls, largest prompt 67 words
[research_lead] 3 calls, largest prompt 203 words
[content_lead] 3 calls, largest prompt 60 words
[flat_lead] 5 calls, largest prompt 237 words
```

The launch lead delegates "establish demand" to the research team. Inside it, the research lead runs its own loop over two workers whose outputs are long (interview notes), then finishes with a two-figure summary. Only that summary reaches the launch lead. The content team does the same for the headline.

The comparison block is the point of the chapter: the hierarchy made **more** coordination calls (9 against 5) but its top-level prompts were **much smaller** (67 words against 237). Both produced the same final headline.

### Why first: why it is built this way

- **`team_as_worker` adapts a Supervisor to the worker interface.** A team becomes `(instruction, state) -> summary`. The top lead cannot tell a team from a single worker, which is the Composite pattern at work.
- **Private state per team run.** `team_as_worker` gives each team a fresh dict; only the summary is written to the parent's state. Leakage would defeat the scoping.
- **Failures become summaries.** A team that does not finish returns `[team failed: reason]` rather than raising, so the parent can decide what to do.
- **The measurement is built in.** The demo prints calls and largest prompt per lead, because "hierarchy helps" is a claim about numbers you should check on your own workload.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Lossy summaries | The top lead decides on missing facts. | Summary contracts with required fields; numbers preserved verbatim. |
| Coordination overhead | Most calls are leads talking to leads. | Flatten levels that have one worker; measure the call mix. |
| Error swallowing | A team fails silently; parent thinks it succeeded. | Explicit failure summaries; status field. |
| Exception propagation | One worker's crash kills the whole tree. | Contain errors at worker boundaries (exercise). |
| Cross-team dependencies | Teams need each other's internals. | Redraw boundaries, or route the shared artefact through parent state. |
| Depth creep | Four levels "for organisation". | Cap depth; justify each level with a context measurement. |

## Variations

- **Heterogeneous teams.** Each team uses a different model size, or a different pattern internally (a chain, a debate).
- **Static hierarchy with dynamic teams.** The top lead spins up a team per subtask from a template.
- **Hierarchical planning.** The top lead plans ([#7](../part-2-single-agent/07-plan-and-execute.md)) and teams execute plan steps.
- **Matrix teams.** A specialist (security review) serves several teams. Use with care: it reintroduces cross-talk.

## Try it

One worker deep inside a team raises an exception, which propagates up and kills the entire hierarchy. Contain failures at the worker boundary so that the team lead sees an error *result*, can finish on its own terms, and the level above receives a summary instead of a crash.

→ Solution: [Solutions — Hierarchical teams](../solutions/13-hierarchical-teams.md)

## 60-second interview lens

- **Say:** "Hierarchical teams are supervisors of supervisors: each team has its own lead, loop and private state, and only summaries flow upward, which keeps every coordinator's context small."
- **Trade-off to name:** more coordination calls in exchange for smaller, more focused contexts. Worth it when per-call context is the problem, not when call count is.
- **Expect the follow-up:** "How do you stop information loss between levels?" Summary contracts with required fields, numbers preserved verbatim, and explicit failure status.
- **Red flag to avoid:** adding levels for neatness without measuring context size or quality.

## Related patterns

- [Supervisor (#12)](12-supervisor.md): one level; the building block.
- [Orchestrator–workers (#4)](../part-1-workflow/04-orchestrator-workers.md): one-pass decomposition, no nested coordinators.
- [Context management (#20)](../part-4-cross-cutting/20-context-management.md): the same goal (bounded context) within a single agent.
- [Coding-team capstone](../capstones/coding-team.md): tech lead over dev and QA teams.
