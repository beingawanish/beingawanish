# 17. Human-in-the-loop

> **Intent.** Pause an agent's risky actions at a checkpoint chosen by code policy, persist the paused state durably, let a person approve, edit or reject (possibly hours later, in a different process), and resume so that each approved action executes exactly once.

**Also known as:** approval gate, human checkpoint, interrupt-and-resume · **Part:** 3 — Multi-agent coordination · **Code:** `code/patterns/human_in_the_loop/` *(canonical module, imported by the support-triage capstone)*

## Structure

![Human-in-the-loop structure](../diagrams/human_in_the_loop.svg)

An agent proposes an action. A code policy checks it: amount limits, irreversibility, model confidence. Safe actions execute immediately. Risky ones become requests in a durable review queue (a JSON file here; a database in production). A reviewer approves, edits or rejects. Resume marks the request as executing *before* the side effect (write-ahead), runs it, and marks it executed. Requests not decided by their deadline expire to rejected.

## Design concept & theory

**Core idea.** Some decisions should not be fully automated: the cost of a mistake is high, the action is irreversible, or the model is unsure. HITL makes "ask a person" a first-class, reliable step in the workflow rather than an exception handler.

**Why it works.**

- *Policy in code, not in the model.* Whether a refund needs approval is decided by `amount > 100`, not by asking the agent whether it thinks it needs oversight. A model must never decide its own supervision.
- *Durability turns waiting into a state.* People take minutes or days. Holding a process open that long is fragile. Persisting the request (action, reasons, context, deadline) means the agent's process can exit, and *any* process can resume later. The example uses three separate "processes" over one file.
- *Exactly-once needs a write-ahead mark.* Resume can be called twice (a retry, or a duplicate click). Recording `executed` makes a second resume a no-op. Recording `executing` *before* the side effect means a crash in between becomes `needs-reconcile` rather than a silent double refund.
- *Silence is not consent.* Undecided requests expire to *rejected*. A default-allow timeout would turn reviewer absence into automatic approval of exactly the actions that needed review.

**Invariants.** (1) A code policy decides what needs review. (2) Paused state is persisted durably. (3) Each approved action executes at most once. (4) Expiry defaults to deny.

**Lineage.** Maker–checker controls; durable workflow engines (sagas, human tasks in BPM); the two-phase commit's "prepare, then commit" applied to a person.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| An action is irreversible, high-value or regulated. | The action is trivially reversible. Undo beats approve. |
| Model confidence is low and errors are costly. | Volume is so high that review becomes rubber-stamping. Fix the policy or automation first. |
| Accountability requires a named human decision. | Latency must be sub-second for every request. |
| You can define the risky subset precisely in code. | Nobody is staffed to review, or no deadline and default can be set. |

**Cheaper alternative:** automatic execution with *undo* (soft delete, refund reversal window) plus sampling-based audit. Upgrade to HITL when undo is impossible or too costly, or when rules require prior approval.

## Forces & trade-offs

| Force | vs. full automation | Why |
|---|---|---|
| Latency | ↑↑ for gated actions | Minutes to days of human time, for the gated subset only. |
| Cost | ↑ (people) | Reviewer time; queue infrastructure. |
| Reliability | ↑ | High-risk errors caught; accountability recorded. |
| Complexity | ↑ | Durable state, idempotent resume, expiry, review UI. |

## Trade-off analysis & usage guidance

**Model.** Let *g* be the gated fraction, *t_h* the human decision time and *c_h* the reviewer cost per decision. Median latency stays automated for (1 − *g*) of actions. Review cost = *g × volume × c_h*. Tune the policy so *g* is as small as safety allows. In the example, 1 of 4 proposed actions runs automatically and 3 are held.

**Decision checklist.**

1. Which actions need review, written as code predicates?
2. Where does paused state live, and does it survive a restart?
3. What happens on a duplicate resume, or a crash mid-execution?
4. What is the deadline, and is the default *deny*?
5. Can the reviewer *edit* (change the amount), not just approve or reject?

**Usage in production.**

- Show reviewers the context: the ticket, the agent's reasoning, the policy reasons that fired.
- Measure approval rate per rule. A rule approved 99.9% of the time is a candidate for automation; one rejected often signals agent problems.
- Pass the request id to the executor as an idempotency key, so the downstream system also refuses duplicates.
- Treat `needs-reconcile` as a page. A side effect in an unknown state is an incident.

## Worked example

### Example first: what happens

```
python3 code/patterns/human_in_the_loop/main.py
```

<!-- expected-output: code/patterns/human_in_the_loop/main.py -->
```text
Human-in-the-loop
=================
-- process 1 (hour 0): agent proposes actions
[executed] refund {'customer': 'sam', 'amount': 20} auto: no policy rule fired
[pending] refund {'customer': 'lee', 'amount': 140} R001 refund $140 > $100
[pending] close_account {'customer': 'kim'} R002 irreversible action
[pending] refund {'customer': 'ana', 'amount': 35} R003 low confidence 0.55
-- process 2 (hour 3): reviewer works the queue
[pending] R001, R002, R003
[resume R001] executed — edit by maya
[resume R002] rejected — customer has open dispute
[resume R001] already-executed — idempotent: not re-run
-- process 3 (hour 30): nobody decided R003
[expired] R003
[resume R003] expired — default deny
ledger: refund(amount=20, customer=sam) | refund(amount=100, customer=lee)
```

In **process 1**, the agent proposes four actions. A $20 refund runs automatically. A $140 refund (over $100), an account closure (irreversible) and a low-confidence refund are queued, each with the reason that fired. Then the process exits.

In **process 2**, three hours later, a reviewer loads the queue from disk. Maya edits R001 down to $100 and rejects R002. Resuming R001 executes the *edited* action. Resuming R001 again is a no-op (`already-executed`).

In **process 3**, at hour 30, nobody has decided R003, so it expires and resume refuses it. The ledger shows exactly two side effects.

### Why first: why it is built this way

- **`Policy` is a list of functions returning reasons.** Every queued request records *why* it was held, which is the first thing a reviewer needs.
- **Atomic file writes.** `_save` writes a temp file and renames it, so a crash never leaves a half-written queue.
- **Edits merge over the original payload.** The reviewer changes only what they change, and the rest of the action is preserved.
- **Status is a small state machine:** pending → approved/rejected/expired → executing → executed. `resume` handles every state explicitly, including the awkward ones.
- **Time is injected (`now`).** Expiry is testable and deterministic. Never read the wall clock inside the policy.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Double execution | Two refunds for one approval. | Executed status + idempotency key; write-ahead "executing" mark. |
| Lost pause | Approval arrives; the agent's state is gone. | Persist the full action and context with the request. |
| Default-allow timeout | Unreviewed actions run after a delay. | Expire to rejected; alert on expiries. |
| Rubber-stamping | Reviewers approve everything quickly. | Reduce volume via policy; sample audits; show reasons and context. |
| Model self-exemption | Agent phrases actions to avoid triggers. | Policy on structured fields (amount, kind), not on text. |
| Single approver for huge actions | One person can move large sums. | Dual control (exercise). |

## Variations

- **Approve the plan, not each step.** Review a [plan (#7)](../part-2-single-agent/07-plan-and-execute.md) once, then execute without further gates.
- **Confidence-gated review.** Only low-confidence outputs go to people; the rest are sampled.
- **Human as a handoff target.** A person joins a [handoff graph (#14)](14-sequential-handoffs.md) as an agent.
- **Ask-the-human tool.** The agent can request clarification as a tool call, and the loop pauses for the answer.

## Try it

Add **dual control**: refunds above $500 need approvals from two *different* reviewers before they can execute. One approval leaves the request pending, the same reviewer approving twice does not count twice, and one rejection rejects.

→ Solution: [Solutions — Human-in-the-loop](../solutions/17-human-in-the-loop.md)

## 60-second interview lens

- **Say:** "Human-in-the-loop pauses risky actions at a checkpoint chosen by code policy, persists the paused state, lets a person approve, edit or reject later, and resumes so each approved action executes exactly once."
- **Trade-off to name:** safety and accountability for the gated subset, at the cost of human latency and staffing, so keep the gated fraction small and precise.
- **Expect the follow-up:** "What if the process crashes during execution?" A write-ahead executing mark, an idempotency key at the downstream service, and reconciliation when the state is unknown.
- **Red flag to avoid:** letting the model decide when it needs approval, or approving by default on timeout.

## Related patterns

- [Guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md): code validators decide validity; HITL decides risk.
- [Tool-use loop (#9)](../part-2-single-agent/09-tool-use-loop.md): the in-process confirmation callback this pattern makes durable.
- [Sequential handoffs (#14)](14-sequential-handoffs.md): escalations land here.
- [Support-triage capstone](../capstones/support-triage.md): this module gating refunds and uncertain replies.
