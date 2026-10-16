# 7. Plan-and-execute (with re-planning)

> **Intent.** Have a model write an explicit multi-step plan before acting, execute the steps one by one (often without a large model), and call the planner again only when results invalidate the remaining plan.

**Also known as:** planner–executor, plan-then-act, LLM compiler (variant) · **Part:** 2 — Single-agent reasoning · **Code:** `code/patterns/plan_and_execute/`

## Structure

![Plan-and-execute structure](../diagrams/plan_and_execute.svg)

The planner, a capable model, writes the whole plan as JSON. Code validates it, and an executor runs it step by step, here with plain functions and no model at all. When a step fails, an optional *local repair* in code gets the first chance to fix it. Otherwise the planner sees all results so far and writes a new plan for the *remaining* work, within a re-plan budget.

## Design concept & theory

**Core idea.** Separate *deciding what to do* from *doing it*. Planning is expensive and benefits from a strong model that sees the whole goal; execution is usually mechanical and can be cheap. Re-planning brings back the adaptivity a fixed plan lacks, but only when it is needed.

**Why it works.**

- *Global view.* A plan written up front considers the whole goal at once: ordering, dependencies, budget. ReAct's one-step-ahead reasoning can paint itself into a corner; a planner sees the corner coming.
- *Cost asymmetry.* Plan with the big model once (or a few times); execute *n* steps with tools or a small model. Expected cost ≈ *c_plan × (1 + replans) + n × c_exec*, against ReAct's *n × c_big × (growing context)*.
- *Re-planning as exception handling.* Most steps succeed, so you pay for adaptivity only on failure. That is the same economics as exceptions in code.
- *An inspectable artefact.* The plan can be shown to a user, approved ([HITL, #17](../part-3-multi-agent/17-human-in-the-loop.md)), validated against an action allow-list, and diffed between versions.

**Invariants.** (1) The plan exists as data before execution starts. (2) Execution follows the plan; it does not invent steps. (3) Plan changes go through the planner (or an explicit repair hook) and are recorded as new versions.

**Lineage.** Classical AI planning (STRIPS, HTN) with replanning; the *Interpreter* pattern (plan = program, executor = interpreter); query planning in databases.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The task has several dependent steps you can't fix in code but a model can foresee. | The steps are always the same ([prompt chaining, #1](../part-1-workflow/01-prompt-chaining.md)). |
| Execution steps are expensive or have side effects, so you want to think before acting. | Each step's choice depends heavily on the last observation (ReAct is simpler). |
| You want a plan a human can review or approve. | Tasks are one or two steps; a plan is overhead. |
| Most steps can run without a large model. | The environment changes so fast that plans are stale on arrival. |

**Cheaper alternative:** [ReAct (#6)](06-react.md) for short horizons, or [orchestrator–workers (#4)](../part-1-workflow/04-orchestrator-workers.md) when the subtasks are independent and one pass suffices. Upgrade when ReAct wanders or repeats itself on longer tasks, or when step failures should change the remaining work.

## Forces & trade-offs

| Force | vs. ReAct | Why |
|---|---|---|
| Latency | ≈ to ↓ | No big-model call per step; one planning call up front, more only on failure. |
| Cost | ↓ on long tasks | Execution is cheap; planning is amortised over many steps. |
| Reliability | ↑ on long tasks; ↓ when reality diverges | Global plan avoids dead ends; a stale plan wastes steps until a failure triggers a re-plan. |
| Complexity | ↑ | Plan schema, validation, versioning, re-plan prompt, repair hooks. |

## Trade-off analysis & usage guidance

**Model.** With *n* executed steps, *r* re-plans, planner cost *c_p* and step cost *c_s*:

- Cost = *(1 + r)·c_p + n·c_s*. In the example *r = 1* and *c_s = 0* (tools only): 2 planner calls for the whole task.
- A local repair hook that resolves a failure without the planner lowers *r*; the exercise cuts planner calls from 2 to 1.
- Bound *r* (`max_replans`) and *n* (`max_steps` per plan).

**Decision checklist.**

1. Can a model write the steps before seeing any results? If not, stay with ReAct.
2. Can execution run on tools or a small model?
3. Which failures are mechanical (local repair) and which need judgement (re-plan)?
4. Does anyone need to approve the plan before it runs?
5. What is the re-plan budget, and what happens when it is spent?

**Usage in production.**

- Validate every plan version against an action allow-list, a step cap, and argument schemas.
- Log plan versions and the reason for each re-plan. "Replan rate" by task type is a key metric.
- Give the re-planner *results so far* and the *failure reason*, not the whole history verbatim.
- Make steps idempotent where possible, so a re-plan can safely repeat one.

## Worked example

### Example first: what happens

The goal: an offsite in Porto for 12 people on 14 Nov, under €2,000, and then draft the invite.

```
python3 code/patterns/plan_and_execute/main.py
```

<!-- expected-output: code/patterns/plan_and_execute/main.py -->
```text
Plan-and-execute
================
[plan v1] s1:search_venues → s2:check_availability → s3:get_quote → s4:draft_invite
[exec s1] ok  ['Casa Azul', 'Quinta Verde']
[exec s2] FAIL booked (Casa Azul unavailable)
[plan v2] s2b:check_availability → s3b:get_quote → s4b:draft_invite
[exec s2b] ok  free
[exec s3b] ok  EUR 1800
[exec s4b] ok  Invite: offsite at Quinta Verde on 14 Nov
result: completed; plans written=2, replans=1, steps executed=5, planner calls=2
final: Invite: offsite at Quinta Verde on 14 Nov
```

Plan v1 has four steps. Step `s2` discovers that Casa Azul is booked. The rest of plan v1 (quote and invite for Casa Azul) is now *stale*, and it is never executed. The planner receives the results so far, including the failure note, and writes plan v2 for the remaining work at Quinta Verde. Five steps ran, with two planner calls and zero model calls in execution.

### Why first: why it is built this way

- **The executor is a plain function.** `execute(step, results)` dispatches on `step.action`. Nothing in execution needs a language model, which is the main cost advantage over ReAct.
- **Plans are validated like untrusted input.** `_parse_plan` checks the JSON shape, the action allow-list and the step cap. A plan that names an unknown action never runs.
- **Only the remaining steps are re-planned.** The re-plan prompt carries completed results, so the planner does not redo the venue search. Completed work is never thrown away.
- **Every plan version is kept.** `PlanRun.plans` is the audit trail of how the agent changed its mind.
- **A `repair` hook comes before the planner.** Some failures have a mechanical fix: try the next candidate. The hook lets code handle those for free (see the exercise) and leaves judgement calls to the planner.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Stale plan | Steps keep running after the world changed. | Treat unexpected results as failures; re-plan on them. |
| Re-plan thrash | Every step triggers a re-plan. | Re-plan budget; local repair hooks; better planner context. |
| Hallucinated action | Plan names a tool that does not exist. | Allow-list validation before execution. |
| Lost progress | Re-plan redoes completed steps. | Pass results so far; ask only for the remaining steps. |
| Over-planning | 15-step plans for 3-step tasks. | Step cap; examples of short plans; plan-length metric. |
| Unsafe plan | Plan includes an irreversible action. | Plan review by a human ([#17](../part-3-multi-agent/17-human-in-the-loop.md)) or a policy check before execution. |

## Variations

- **Plan-and-solve prompting.** A single call: "first write a plan, then follow it". The cheap, no-runtime version.
- **Parallel plan execution (LLM compiler).** The plan is a DAG, and independent steps run concurrently via [parallelization (#3)](../part-1-workflow/03-parallelization.md).
- **Hierarchical planning.** Each plan step expands into its own sub-plan. Cap the depth.
- **Plan approval.** The plan is shown to a human before execution, which is the cheapest place to put human oversight.

## Try it

Re-planning costs a large-model call. When an availability check fails and the earlier search already returned other venues, the fix is mechanical: check the next venue and swap it into the remaining steps. Implement this as a `repair` hook and show the planner calls drop from 2 to 1.

→ Solution: [Solutions — Plan-and-execute](../solutions/07-plan-and-execute.md)

## 60-second interview lens

- **Say:** "Plan-and-execute has a strong model write the whole plan as data, a cheap executor run it, and the planner re-plan only the remaining steps when something fails."
- **Trade-off to name:** it is cheaper and more coherent than ReAct on long tasks, but a plan can go stale, so failure detection and a re-plan budget are essential.
- **Expect the follow-up:** "How is this different from orchestrator–workers?" Steps here can depend on each other and the plan is revised on failure. Orchestrator–workers is one pass over independent subtasks.
- **Red flag to avoid:** executing the plan without validating it against an allow-list.

## Related patterns

- [ReAct (#6)](06-react.md): decides one step at a time; simpler for short, observation-driven tasks.
- [Orchestrator–workers (#4)](../part-1-workflow/04-orchestrator-workers.md): single-pass decomposition with no re-planning.
- [Hierarchical teams (#13)](../part-3-multi-agent/13-hierarchical-teams.md): planning and delegation across levels of agents.
- [Deep-research capstone](../capstones/deep-research.md): plan-and-execute driving agentic RAG, with a real re-plan.
