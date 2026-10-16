# 9. Tool-use loop

> **Intent.** Run an agent as a loop in which the model emits one structured tool call at a time and the *host* validates, confirms, executes, and returns the result (or the error) as the next observation, until the model gives a final answer or a host-enforced limit stops it.

**Also known as:** function-calling loop, agent runtime, agent executor · **Part:** 2 — Single-agent reasoning · **Code:** `code/patterns/tool_use_loop/`

## Structure

![Tool-use loop structure](../diagrams/tool_use_loop.svg)

The model replies with exactly one JSON object: a tool call or a final answer. The host validates the call against the tool's schema. Calls to side-effecting tools need confirmation (a person, or a policy). The host executes the call and appends the result, or the error *as text*, to the transcript. Stop conditions (step limit, consecutive errors, budget) belong to the host, not the model.

## Design concept & theory

**Core idea.** This is the minimal, correct runtime under every agent in this book. ReAct, agentic RAG and the coding team's developer are all *policies* running on this loop. This chapter is about the loop itself: the contract between a model that proposes and a host that disposes.

**Why it works: the host is the trusted computing base.**

- *Errors are observations, not exceptions.* A model that calls `list_events(date=20261016)` should *see* "argument 'date' must be str" and fix it on the next step. Raising an exception would end the run, and silently coercing the value would hide the bug. Recovery from errors is the most valuable behaviour a tool loop enables, and it only works if errors are fed back.
- *Validation before execution.* Arguments are checked against the schema *before* the tool runs. Tools never see malformed input, and the model gets a precise error.
- *Separation of proposal and authority.* The model can propose `create_event`; only the host, through a confirmation policy, can let it happen. This is the same principle as [human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md), applied per call.
- *Termination is a host decision.* Models are bad at knowing when they are stuck. Step limits, consecutive-error limits and cost budgets are cheap, deterministic and always on.

**Invariants.** (1) Exactly one structured action per model turn. (2) Every action's result or error is appended before the next turn. (3) The host validates, authorises and terminates.

**Lineage.** The *Command* pattern (a call is a request object the invoker validates and executes); an OS system-call boundary (user code requests, the kernel checks and performs); the event loop.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The model must call tools whose sequence it decides. | A single tool call answers the question (one-shot function calling). |
| Tools can fail and the model should recover. | The sequence is known; call the tools from code ([Part 1](../part-1-workflow/00-part-intro.md)). |
| Some tools have side effects that need gating. | You cannot bound steps or cost: fix that before shipping. |
| You need a runtime other patterns can share. | Real-time constraints forbid several sequential round trips. |

**Cheaper alternative:** a single model call with tool *results pre-fetched by code* (retrieve, then answer). Upgrade when the model needs to choose *which* tools to call or *react* to a result.

## Forces & trade-offs

| Force | vs. pre-fetching in code | Why |
|---|---|---|
| Latency | ↑ | One model round trip per tool call. |
| Cost | ↑ | The transcript grows with every call. |
| Reliability | ↑ in open-ended tasks | Recovery from errors; the model adapts to results. |
| Complexity | ↑ | Schemas, a confirmation policy, transcript management, stop conditions. |

## Trade-off analysis & usage guidance

**Model.** With *k* tool calls, an average transcript growth *g* per call, and a fixed prompt *P*:

- Calls = *k + 1* (the final answer). Prompt tokens ≈ *(k+1)·P + g·k(k+1)/2*.
- Each failed call costs a full step. In the example, one type error made a three-call task take four steps.
- Bound everything: `max_steps`, `max_errors`, and in production a token or cost budget.

**Decision checklist.**

1. Does every tool have a typed schema the host checks?
2. Which tools have side effects, and who confirms them?
3. Do errors come back as text the model can act on?
4. What are the step, error and cost limits, and what does the user see when one trips?
5. Are side-effecting tools idempotent, or deduplicated by the host (exercise)?

**Usage in production.**

- Write tool descriptions for the model: what the tool does, when to use it, argument formats with examples.
- Keep tool results small and structured; truncate large payloads.
- Log every call with arguments, result status and latency. Per-tool error rate is the best signal of a confusing schema.
- Use an allow-list per task: an agent booking meetings does not need `delete_account` in its tool set.

## Worked example

### Example first: what happens

```
python3 code/patterns/tool_use_loop/main.py
```

<!-- expected-output: code/patterns/tool_use_loop/main.py -->
```text
Tool-use loop
=============
-- Book a 30-minute sync with Dana tomorrow afternoon (2026-10-16)
[call 1] list_events({"date": 20261016})
[result 1] ERROR: list_events: argument 'date' must be str
[call 2] list_events({"date": "2026-10-16"})
[result 2] [{"title": "Design review", "start": "13:00", "end": "14:00"}]
[call 3] create_event({"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"})
[result 3] {"created": true, "title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}
[final] Booked Sync with Dana on 2026-10-16, 14:00-14:30 (after your design review).
result: final in 4 steps; confirmations asked: ['create_event']
-- Summarise my week
[call 1] list_events({"date": "2026-10-16"})
[result 1] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[call 2] list_events({"date": "2026-10-16"})
[result 2] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[call 3] list_events({"date": "2026-10-16"})
[result 3] [{"title": "Design review", "start": "13:00", "end": "14:00"}, {"title": "Sync with Dana", "date": "2026-10-16", "start": "14:00", "end": "14:30"}]
[stop] step limit 3 reached
result: max_steps, final=None
```

**Booking:** the first call passes the date as an integer. The registry rejects it *before* the tool runs and returns the error as an observation. The model fixes the type, reads the existing 13:00–14:00 meeting, and proposes a 14:00 slot. `create_event` is side-effecting, so the host asks for confirmation (recorded as `['create_event']`) before executing. Then the model finishes.

**"Summarise my week":** a model that never decides it is done calls `list_events` again and again. The host stops it at the step limit with `final=None`, rather than letting it run until the money runs out.

### Why first: why it is built this way

- **`ToolRegistry` validates; `ToolLoop` orchestrates.** Schemas and type checks live with the tools, and the loop stays generic. Any registry-compatible object works, which is how the exercise adds idempotency without touching the loop.
- **Confirmation is a callback.** `confirm(name, args) -> bool` might be a UI prompt, a policy check, or a [review queue (#17)](../part-3-multi-agent/17-human-in-the-loop.md). The loop does not care which.
- **`render` is pluggable.** The coding-team capstone passes a [context manager (#20)](../part-4-cross-cutting/20-context-management.md) here so long transcripts are compacted. The loop logic is unchanged.
- **Consecutive errors, not total errors.** An agent that makes and then fixes a mistake is working. One that fails three times in a row is not.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Runaway loop | Repeated calls, no final answer. | Step cap; cost budget; repeated-call detection. |
| Malformed calls | Wrong types, missing args. | Schema validation before execution; error text with the fix. |
| Duplicate side effects | Two identical bookings or payments. | Idempotency keys; host-side dedupe (exercise). |
| Unauthorised action | A destructive tool called without consent. | Confirmation policy; per-task tool allow-lists. |
| Error spiral | Model keeps retrying the same failing call. | Consecutive-error limit; include the corrective hint in the error. |
| Prompt injection via results | Tool output contains instructions. | Treat tool output as data; never let it change permissions; quote or label it in the transcript. |

## Variations

- **Parallel tool calls.** The model emits several independent calls per turn and the host runs them concurrently ([#3](../part-1-workflow/03-parallelization.md)).
- **Native function calling.** The provider's API carries tool schemas and calls as structured fields. Same loop, less parsing.
- **Tool search / progressive disclosure.** With hundreds of tools, expose a `find_tool` tool and load full schemas on demand ([#20](../part-4-cross-cutting/20-context-management.md)).
- **Sandboxed execution.** Code-executing tools run in an isolated process with resource limits.

## Try it

A model that loses track of progress may call `create_event` twice with identical arguments, double-booking the meeting. Make side-effecting tools **idempotent in the host**: an identical repeat call returns the earlier result with a `duplicate_ignored` note and never re-executes. Do not change `ToolLoop`.

→ Solution: [Solutions — Tool-use loop](../solutions/09-tool-use-loop.md)

## 60-second interview lens

- **Say:** "The tool-use loop is the agent runtime: the model proposes one structured call, the host validates, authorises and executes it, feeds back the result or the error, and owns every stop condition."
- **Trade-off to name:** flexibility and error recovery in exchange for one round trip per call and a growing transcript, so bound steps, errors and cost.
- **Expect the follow-up:** "How do you handle a tool error?" Return it as an observation with enough detail to fix, count consecutive errors, and stop at a limit. Never crash the loop, and never hide the error.
- **Red flag to avoid:** letting the model decide when to stop with no host-side limit.

## Related patterns

- [ReAct (#6)](06-react.md): a reasoning format that runs on this loop with visible thoughts.
- [Human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md): the durable version of the confirmation callback.
- [Context management (#20)](../part-4-cross-cutting/20-context-management.md): keeps the growing transcript within budget.
- [Coding-team capstone](../capstones/coding-team.md): this loop drives the developer agent.
