# 6. ReAct

> **Intent.** Let a model alternate between writing down a *thought*, taking an *action* with a tool, and reading the *observation*, in one growing trace, so that every next step is grounded in what was actually observed.

**Also known as:** reason + act, thought–action–observation loop · **Part:** 2 — Single-agent reasoning · **Code:** `code/patterns/react/`

## Structure

![ReAct structure](../diagrams/react.svg)

The model reads the whole trace so far and writes a Thought and an Action (`tool[input]`). Code parses the action, runs the tool, and appends the Observation to the trace. The loop repeats until the model writes a Final Answer. A step limit and a repeated-action guard stop it when it is not making progress.

## Design concept & theory

**Core idea.** Reasoning without acting hallucinates; acting without reasoning flails. ReAct interleaves the two at the granularity of a single step: think about what you know, do one thing to learn more, look at the result, think again.

**Why it works.**

- *Grounding.* Each thought is written *after* the latest observation is in the context. Facts the model would otherwise invent ("Orbit X1 is made by…") are instead looked up, and the lookup result is right there for the next step to use.
- *Adaptivity.* The plan is implicit and one step deep. When an observation surprises the model ("No results."), the very next thought can change course. In the example, an over-specific search fails and the agent broadens it.
- *Legibility.* The trace *is* the explanation. You can read why the agent did each thing, which is the main reason to choose ReAct over a silent tool loop.
- *The cost is quadratic-ish context.* Each step re-sends the whole trace. Over *n* steps, prompt tokens grow roughly as *n²/2 × step size*. ReAct is for short horizons (a handful of steps); long ones need [plan-and-execute (#7)](07-plan-and-execute.md) or [context management (#20)](../part-4-cross-cutting/20-context-management.md).

**Invariants.** (1) One action per step, and its observation is appended before the next thought. (2) The trace format is fixed and machine-parseable. (3) The host enforces termination; the model only *proposes* finishing.

**Lineage.** The OODA loop (observe–orient–decide–act); the read–eval–print loop with commentary. In research, the 2022 ReAct paper (Yao et al.) named the prompting format.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| The next step depends on what the last tool returned (multi-hop lookup, debugging). | The steps are known in advance ([prompt chaining, #1](../part-1-workflow/01-prompt-chaining.md)). |
| You need a human-readable reasoning trail for audit or debugging. | The task is long-horizon (dozens of steps). Context and cost grow every step. |
| Tasks are short: a few hops, not dozens. | Visible "thoughts" would leak sensitive reasoning to end users. |
| Tools are cheap and safe to call speculatively. | Every action has expensive side effects; plan first ([#7](07-plan-and-execute.md)). |

**Cheaper alternative:** a single tool-calling turn (model picks one tool, answers from its result), or a [tool-use loop (#9)](09-tool-use-loop.md) without explicit thoughts. Upgrade to ReAct when multi-hop questions fail because the model does not reason about intermediate results, or when you need the trace.

## Forces & trade-offs

| Force | vs. a plain tool loop | Why |
|---|---|---|
| Latency | ↑ | Thoughts are extra output tokens every step; steps are sequential. |
| Cost | ↑ | Whole trace re-sent each step, plus thought tokens. |
| Reliability | ↑ on multi-hop | Explicit intermediate reasoning reduces skipped hops and unjustified leaps. |
| Complexity | ≈ | A parser and two guards on top of a tool loop. |

## Trade-off analysis & usage guidance

**Model.** With *n* steps, a fixed prompt *P*, and an average step size *s* (thought + action + observation):

- Prompt tokens ≈ *n·P + s·n(n−1)/2*. The second term dominates past a few steps.
- Latency ≈ *n × (model time + tool time)*.
- In the example: 5 steps for a 3-hop question (one wasted on an empty search), 7 model calls in total across both questions.

**Decision checklist.**

1. Does the next step depend on the last observation? If not, use a chain.
2. Is the horizon short (under ~8 steps)? If not, plan first or compact.
3. Are tools safe to call exploratorily?
4. Will someone read the trace? If nobody will, the thoughts are cost without benefit; use a tool loop.
5. Do you have a stop rule beyond "the model says it's done"?

**Usage in production.**

- Cap steps and detect repeated actions; both are cheap and catch most loops.
- Keep observations short: truncate or summarise tool output before appending, because it is re-sent every step.
- Log the trace verbatim. It is your debugging record.
- Do not show raw thoughts to end users by default; they can contain guesses the final answer rightly discards.

## Worked example

### Example first: what happens

```
python3 code/patterns/react/main.py
```

<!-- expected-output: code/patterns/react/main.py -->
```text
ReAct
=====
-- Q1: What's the weather at the HQ of the company that makes the Orbit X1?
[thought 1] First find who makes the Orbit X1 headset.
[action 1] search[Orbit X1 headset maker]
[observe 1] No results.
[thought 2] The phrase was too specific; search the product name alone.
[action 2] search[Orbit X1]
[observe 2] Orbit X1 is a VR headset made by Lumen Labs.
[thought 3] The maker is Lumen Labs; find where it is headquartered.
[action 3] search[Lumen Labs]
[observe 3] Lumen Labs is headquartered in Lisbon, Portugal.
[thought 4] The HQ is Lisbon; now get the weather there.
[action 4] weather[Lisbon]
[observe 4] Lisbon: 21°C, sunny
[thought 5] I have the city and its weather.
[final] Lisbon — currently 21°C and sunny.
result: answered in 5 steps
-- Q2: What is the Lumen Labs CEO's shoe size?
[thought 1] I should search for the CEO's shoe size.
[action 1] search[Lumen Labs CEO shoe size]
[observe 1] No results.
[thought 2] I should search for the CEO's shoe size.
[stop] repeated action search[Lumen Labs CEO shoe size] — not making progress
result: repeated_action after 2 steps, answer=None
model calls: 7
```

**Q1** needs three hops: product → maker → headquarters → weather. The first search is too specific and returns *No results*. The next thought reacts to that observation and broadens the query, which is exactly the adaptivity ReAct is for. From there each observation feeds the next action, and the final answer uses only what was observed.

**Q2** asks for something no tool can know. The model repeats the identical search, and the *repeated-action guard* stops the loop after two steps instead of letting it spin until the step limit.

### Why first: why it is built this way

- **One regex for actions, one for the final answer.** A strict, line-oriented format is easy for models to follow and trivial to parse. Anything else becomes an "Invalid format" *observation*, so the model can fix it, rather than an exception.
- **Tool errors are observations too.** `ToolError` text is appended like any result, so the agent can see "No weather data for X" and adapt.
- **The repeated-action guard compares (tool, input) pairs.** Repeating an action with identical input cannot produce new information in a deterministic tool world, so it is a reliable "stuck" signal and much cheaper than waiting for `max_steps`.
- **The mock reasons from the trace.** It chooses each step by checking what observations are present, which mirrors how the real pattern works. Read `model()` in `main.py` as a specification of good ReAct behaviour.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Looping | Same action repeated; no new information. | Repeated-action detection; step cap. |
| Ungrounded final answer | Final answer states facts no observation contains. | Post-hoc grounding check (the exercise); require citations to observations. |
| Format drift | Model writes two actions, or prose instead of `Action:`. | Strict parser; invalid format becomes an observation asking for the format. |
| Context blow-up | Long tool outputs re-sent every step. | Truncate or summarise observations; [compaction (#20)](../part-4-cross-cutting/20-context-management.md). |
| Premature finish | Final answer after one hop, skipping verification. | Prompt examples showing multi-hop; check required facts in code where possible. |
| Thought leakage | Speculative reasoning shown to users. | Show only the final answer; keep traces internal. |

## Variations

- **ReAct with native tool calls.** The model emits structured tool calls and the thoughts go in a separate text field. This is the same pattern, running on the [tool-use loop (#9)](09-tool-use-loop.md) runtime.
- **ReAct + reflection.** After a failed episode, write a lesson and retry (Reflexion). See [reflection (#8)](08-reflection.md) and its exercise.
- **Self-ask.** The thought is always a sub-question; the action is always a search. This is a narrowed ReAct for multi-hop QA.
- **Budgeted ReAct.** The trace header shows remaining steps and cost, so the model can trade thoroughness for budget explicitly.

## Try it

A model can skip the tools and write a confident `Final Answer` from memory. Write a **post-hoc grounding check**: every number and capitalised name in the final answer must appear in some Observation. Show it passing the real Q1 run and flagging an answer produced with no tool calls.

→ Solution: [Solutions — ReAct](../solutions/06-react.md)

## 60-second interview lens

- **Say:** "ReAct interleaves a written thought, one tool action and its observation in a growing trace, so each decision is grounded in what was actually observed."
- **Trade-off to name:** the trace makes it adaptive and auditable, but the whole trace is re-sent every step, so cost grows roughly quadratically and it suits short horizons.
- **Expect the follow-up:** "How do you stop it looping?" A step cap, repeated-action detection, and treating errors as observations so the model can recover rather than retry blindly.
- **Red flag to avoid:** confusing ReAct (a reasoning *format*) with the tool-use loop (the *runtime*); they compose.

## Related patterns

- [Tool-use loop (#9)](09-tool-use-loop.md): the runtime mechanics (schemas, dispatch, confirmation, termination) ReAct runs on.
- [Plan-and-execute (#7)](07-plan-and-execute.md): decides the whole sequence up front instead of one step at a time.
- [Agentic RAG (#10)](10-agentic-rag.md): a specialised ReAct where the action is always retrieval and observations are graded.
- [Reflection (#8)](08-reflection.md): learn from a failed trajectory before the next attempt.
