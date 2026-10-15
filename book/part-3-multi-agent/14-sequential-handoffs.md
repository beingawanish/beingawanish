# 14. Sequential handoffs

> **Intent.** Let exactly one agent own a live conversation at a time, and let the owner transfer that ownership to a better-suited agent with an explicit handoff object (target, reason, summary), with no central coordinator.

**Also known as:** agent handoff, transfer of control, relay · **Part:** 3 — Multi-agent coordination · **Code:** `code/patterns/sequential_handoffs/`

## Structure

![Sequential handoffs structure](../diagrams/sequential_handoffs.svg)

The user talks to whichever agent currently owns the conversation. The owner either replies or hands off. A handoff carries a target, a reason and a summary, and the new owner starts with that brief plus the recent transcript. The runtime has no opinion about content. It enforces only the allowed handoff graph, a per-turn handoff cap, and a ping-pong guard that escalates to a human.

## Design concept & theory

**Core idea.** Many conversations change topic: a billing question becomes a technical one. Instead of a coordinator in the middle of every exchange, the current specialist recognises it is no longer the right owner and passes the conversation on, the way a good support desk transfers a call *with a summary*.

**Why it works.**

- *Ownership is unambiguous.* At any moment exactly one agent is responsible, so there is no supervisor to consult, no committee and no conflicting replies. That makes conversations fast and the transcript easy to follow.
- *The handoff object is the contract.* A summary like "duplicate March charge already refunded; now: app crashes opening Reports" lets the next agent pick up without re-asking. In the example the technical agent opens by acknowledging the refund it never processed.
- *Local decisions scale.* Each agent only needs to know its own scope and its allowed targets. Adding a new specialist means adding it to some agents' handoff lists, not retraining a central router.
- *But nothing global watches the whole.* Without a coordinator, cycles are possible: billing thinks it is an account matter, and account thinks it is billing. The ping-pong guard is the minimum global property the runtime must enforce.

**Invariants.** (1) One owner at a time. (2) Ownership moves only through an explicit handoff object. (3) The runtime enforces the handoff graph and cycle limits; it does not coordinate content.

**Lineage.** Call transfer in contact centres; the *Chain of Responsibility* pattern (a request passes along handlers until one handles it), with the chain chosen at runtime; the *State* pattern, where the active agent is the conversation's state.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| Conversations drift between domains handled by different specialists. | The steps are known in advance ([prompt chaining, #1](../part-1-workflow/01-prompt-chaining.md)). |
| Each specialist needs its own tools and instructions. | Work must be combined from several specialists at once ([supervisor, #12](12-supervisor.md)). |
| Low latency matters: no coordinator call on every turn. | Nobody can define which agent may hand off to which. |
| A summary is enough context for the next owner. | Every agent needs the full history verbatim; handoff summaries will lose too much. |

**Cheaper alternative:** a [router (#2)](../part-1-workflow/02-routing.md) at the start of each *user turn*, with no ownership. Upgrade to handoffs when specialists need to carry state across turns, or decide themselves that the topic has moved on.

## Forces & trade-offs

| Force | vs. a supervisor | Why |
|---|---|---|
| Latency | ↓ | No coordinator call per turn; one extra call only at a handoff. |
| Cost | ↓ | Owners act directly; handoffs are rare events. |
| Reliability | ≈, with different risks | No coordinator bottleneck, but cycles and lossy summaries are possible. |
| Complexity | ↓ in the runtime, ↑ in the graph design | A tiny runtime; the handoff graph and summaries need care. |

## Trade-off analysis & usage guidance

**Model.** Calls per user turn = 1 + (handoffs in that turn). In conversation 1 of the example: turn 1 = 2 calls (triage hands off, billing replies), turn 2 = 2, and turn 3 = 1. A supervisor design would pay at least one extra coordinator call on *every* turn.

**Designing the graph.** Draw the allowed handoffs as a directed graph. Every edge should have a reason you could write down. Then check the cycles: each cycle is a potential ping-pong the guard will have to catch.

**Decision checklist.**

1. Can each agent's scope be stated in one sentence?
2. Is the allowed handoff graph explicit, and are its cycles intentional?
3. What must a handoff summary contain for the next owner to continue without re-asking?
4. What happens on ping-pong or an invalid target: escalation, and to whom?
5. How many handoffs per user turn are acceptable? Usually ≤ 2.

**Usage in production.**

- Log every handoff (from, to, reason). Handoff-reason histograms reveal mis-scoped agents.
- Measure re-asking: a new owner asking for information the user already gave means the summaries are lossy.
- Escalate to a human with the full transcript, never just the last summary.
- Keep the ping-pong guard per user turn, and track repeated cycles across turns too.

## Worked example

### Example first: what happens

```
python3 code/patterns/sequential_handoffs/main.py
```

<!-- expected-output: code/patterns/sequential_handoffs/main.py -->
```text
Sequential handoffs
===================
-- conversation 1
[user] Hi, I was charged twice for March.
[triage ⇒ billing] billing issue | summary: Customer reports a duplicate March charge.
[billing] Found it — the duplicate March charge is refunded; expect it in 3-5 days.
[user] Thanks! Also the app crashes when I open Reports.
[billing ⇒ technical] app crash | summary: Duplicate March charge already refunded. Now: app crashes opening Reports.
[technical] I can see billing already refunded your duplicate charge. The Reports crash is fixed in 3.2.1 — please update and reopen.
[user] Updated — that fixed it.
[technical] Glad to hear it! Your refund is still on its way. Anything else?
owner now: technical; handoffs: triage → billing → technical
-- conversation 2
[user] Can you change my plan and fix my login?
[triage ⇒ billing] plan change | summary: Wants to change plan; also login.
[billing ⇒ account] plans are account settings | summary: Plan change requested.
[escalate] ping-pong: triage → billing → account → billing
escalated: True
```

**Conversation 1:** triage hands the duplicate-charge complaint to billing, which resolves it and keeps ownership. When the customer raises a crash, billing hands off to technical, and its summary records that the refund is done. Technical acknowledges the refund, fixes the crash, and stays the owner for the customer's thank-you.

**Conversation 2:** triage → billing → account → billing. The runtime detects the cycle (billing would become the owner a second time in the same turn) and escalates to a human instead of letting two agents bounce the customer.

### Why first: why it is built this way

- **`visited` is per user turn.** Revisiting an agent across turns is normal (billing could take the conversation back next week); revisiting within one turn means nobody is willing to own it.
- **The handoff graph is data on each agent** (`can_handoff_to`). A handoff outside it is refused by the runtime, not trusted, because an agent's model can name any string.
- **The brief goes into the prompt, not the transcript.** The new owner sees "HANDOFF from billing: app crash. Summary: …" once, at the moment of transfer. The user-visible transcript stays clean.
- **Escalation is fixed text.** The user gets a predictable message, and the transcript gets a `SYSTEM: escalated (…)` line for the human picking it up.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Ping-pong | Agents bounce the conversation. | Per-turn visited set; escalate on a cycle. |
| Invalid target | Handoff to a non-existent or disallowed agent. | Graph validation; one corrective re-ask (exercise), then escalate. |
| Lossy summary | New owner re-asks known facts. | Required summary fields; measure re-asking. |
| Reluctant owner | Every agent hands off; nobody answers. | Handoff cap per turn; scope instructions with examples. |
| Sticky owner | Agent answers outside its scope instead of handing off. | Scope tests in the eval set; out-of-scope detection. |

## Variations

- **Handoff with return.** A specialist takes the conversation for a subtask and hands it back automatically.
- **Human as a node.** A human agent in the graph, reachable by handoff ([#17](17-human-in-the-loop.md)).
- **Router entry.** The entry agent is a pure [router (#2)](../part-1-workflow/02-routing.md) that never answers. That is triage in the example.
- **Structured handoff payload.** Typed fields (customer id, completed actions, open questions) instead of a free-text summary.

## Try it

The technical agent tries to hand off to `refunds`, an agent that does not exist, and the runtime escalates the whole conversation. Give the agent **one chance to correct** an invalid target (tell it the valid targets) before escalation applies, without modifying `HandoffRuntime`.

→ Solution: [Solutions — Sequential handoffs](../solutions/14-sequential-handoffs.md)

## 60-second interview lens

- **Say:** "With sequential handoffs, one agent owns the conversation at a time and transfers ownership with an explicit handoff object (target, reason, summary), with no central coordinator."
- **Trade-off to name:** lower latency and cost than a supervisor, but nothing global watches the conversation, so you need a handoff graph, cycle detection and good summaries.
- **Expect the follow-up:** "How is this different from prompt chaining?" Chain steps are fixed calls owned by one program; handoffs move a live conversation between autonomous agents, and the target is chosen at runtime.
- **Red flag to avoid:** handoffs without a summary, which force the next agent to re-interview the user.

## Related patterns

- [Prompt chaining (#1)](../part-1-workflow/01-prompt-chaining.md): a fixed sequence of calls, not agents transferring ownership.
- [Routing (#2)](../part-1-workflow/02-routing.md): one-shot dispatch without ownership.
- [Supervisor (#12)](12-supervisor.md): a central coordinator decides every turn instead.
- [Human-in-the-loop (#17)](17-human-in-the-loop.md): where escalations should land.
