# 5. Evaluator–optimizer

> **Intent.** Pair a generator with a *separate* evaluator that judges each draft against an explicit rubric and returns actionable feedback, looping until the draft passes, a round budget is spent, or progress stalls.

**Also known as:** generate–critique–revise, LLM-as-judge loop, iterative refinement · **Part:** 1 — Workflow · **Code:** `code/patterns/evaluator_optimizer/`

## Structure

![Evaluator–optimizer structure](../diagrams/evaluator_optimizer.svg)

The generator writes a draft. The evaluator, a different role with its own rubric, returns pass or fail plus one fix per failed criterion. Failing feedback flows back to the generator for revision. Code ends the loop on a pass, on a round budget, or on a stall (the same feedback twice), and in the last two cases escalates.

## Design concept & theory

**Core idea.** Getting something right on the first try is hard; recognising what is wrong with a draft is often easier. The pattern exploits that asymmetry by separating the two jobs and iterating.

**Why it works.**

- *The generation–verification gap.* For many tasks, checking a candidate against criteria is more reliable than producing a candidate that meets them. The evaluator only has to say *which criterion fails and what would fix it*; the generator only has to apply a specific fix. Each call does the easier half of the problem.
- *Explicit rubrics turn vague quality into checkable claims.* "Write a good apology" has no failure signal. "Offers a concrete remedy" does. A rubric is also where business rules enter: no blame, no promises we cannot keep.
- *Separation reduces self-agreement.* A model asked to critique its *own* draft in the same context tends to approve it. A separate evaluator call, with its own instructions ("you did not write this") and ideally a different model, behaves more like a reviewer. This is the line between this pattern and [reflection (#8)](../part-2-single-agent/08-reflection.md).
- *Iteration has diminishing returns.* Most of the gain arrives in the first one or two revisions. Expected cost grows linearly with rounds while quality improvement flattens, which is why the loop needs a budget and a stall detector, not just a pass condition.

**Invariants.** (1) Generator and evaluator are distinct roles with distinct prompts. (2) The evaluator judges against an explicit rubric and returns *actionable* feedback. (3) Code owns termination. If the check is deterministic code rather than a judgement, the pattern is [guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md). If both sides are tool-using agents trading itemised review comments, it is the [critic–reviewer loop (#16)](../part-3-multi-agent/16-critic-reviewer.md).

**Lineage.** A closed-loop feedback controller (setpoint = rubric, error signal = feedback); *test-driven* revision; loosely, the actor–critic split from reinforcement learning, without any learning, since nothing is updated between tasks.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| Quality criteria can be stated, and a reviewer can tell when they are met. | Criteria are purely subjective or cannot be articulated. |
| First drafts are often *close* but miss specific criteria. | First drafts are usually fine. You would pay ×2–×6 for nothing. |
| Feedback can be specific enough for a revision to act on. | The criterion is checkable in code (length, schema, regex): use a validator (#11), which is cheaper and exact. |
| Latency allows several sequential rounds. | The generator lacks the information to fix the problem. No feedback helps; escalate instead. |

**Cheaper alternative:** a single generation with the rubric in the prompt, plus deterministic checks for whatever criteria are mechanical. Upgrade when you can show, on an eval set, that rubric failures are frequent *and* fixable by revision.

## Forces & trade-offs

| Force | vs. single generation | Why |
|---|---|---|
| Latency | ↑↑ | Each round is two sequential calls; three rounds ≈ six calls of latency. |
| Cost | ↑↑ | Rounds × (generator + evaluator). Evaluator prompts include the draft *and* the rubric. |
| Reliability | ↑ on stated criteria | Failures against the rubric are caught and usually fixed; unstated criteria are not. |
| Complexity | ↑ | Rubric design, feedback format, termination logic, evaluator calibration. |

## Trade-off analysis & usage guidance

**Model.** With generator cost *c_g*, evaluator cost *c_e*, and *R* rounds used (≤ budget *B*):

- Cost = *R·(c_g + c_e)*. Worst case *B·(c_g + c_e)*. Set *B* from the eval set's distribution of rounds-to-pass: typically 2–3.
- Latency = *R·(t_g + t_e)*, all sequential.
- Every criterion you move from the evaluator to code (as the exercise does for word count) cuts both cost and variance.

**Decision checklist.**

1. Can you write the rubric as 3–6 criteria, each answerable yes/no?
2. Which criteria are checkable in code? Move those out of the evaluator.
3. Does feedback name a *specific fix*, not just a score?
4. What happens when the budget runs out: ship best effort, flag it, or escalate?
5. Is the evaluator a different prompt, and ideally a different model, from the generator?

**Usage in production.**

- Log every round's draft and feedback. Rounds-to-pass by task type is the key metric.
- Detect stalls: the same feedback twice means more rounds will not help. Stop and escalate.
- Calibrate the evaluator against human labels on a sample (see [eval harness, #21](../part-4-cross-cutting/21-eval-harness.md)). An evaluator that passes everything is a cost with no benefit.
- Use a cheaper model for the evaluator only if calibration shows it agrees with the stronger one.

## Worked example

### Example first: what happens

An apology email must meet four criteria: acknowledges the order and delay, offers a concrete remedy, no blame, under 60 words.

```
python3 code/patterns/evaluator_optimizer/main.py
```

<!-- expected-output: code/patterns/evaluator_optimizer/main.py -->
```text
Evaluator-optimizer
===================
-- Apology to Sam: order #4471 arrived 6 days late
[round 1 draft] Hi Sam, sorry order #4471 was late — the courier had problems. We'll make it up to you somehow.
[round 1 eval] FAIL: Remove blame on the courier; take ownership; Offer a concrete remedy, e.g. refund the shipping fee
[round 2 draft] Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. We'll make it up to you.
[round 2 eval] FAIL: Offer a concrete remedy, e.g. refund the shipping fee
[round 3 draft] Hi Sam, I'm sorry order #4471 arrived 6 days late. That's on us. I've refunded your $9.99 shipping fee today and added free express shipping to your next order.
[round 3 eval] PASS
result: passed=True rounds=3 stop=passed
-- Reply to Lee promising same-day delivery tomorrow
[round 1 draft] Hi Lee, we guarantee same-day delivery tomorrow!
[round 1 eval] FAIL: Same-day delivery cannot be guaranteed; do not promise it
[round 2 draft] Hi Lee, we guarantee same-day delivery tomorrow!
[round 2 eval] FAIL: Same-day delivery cannot be guaranteed; do not promise it
result: passed=False rounds=2 stop=stalled -> escalate to a human
total model calls: 10
```

*Apology to Sam.* Round 1 blames the courier and offers a vague remedy, and the evaluator returns two fixes. Round 2 fixes only one, as real models often do. Round 3 fixes the other and passes. Each round the feedback names exactly what remains.

*Reply to Lee.* The task asks for something the rubric forbids (guaranteeing same-day delivery). The generator cannot satisfy both, so the evaluator returns identical feedback twice and the loop stops as *stalled* after two rounds instead of burning the budget. The right outcome is escalation to a human. More rounds would not fix this.

### Why first: why it is built this way

- **Feedback is a list of fixes, not a score.** `{"pass": false, "feedback": ["Remove blame…", "Offer a concrete remedy…"]}` tells the generator what to change. A score of 6/10 does not.
- **The revision prompt carries the previous draft *and* all outstanding feedback.** The generator edits rather than starting over, which converges faster and keeps what was already right.
- **Three stop reasons, all explicit.** `passed`, `budget`, `stalled`. Callers branch on `stop_reason`, so a stalled loop can route to a human rather than ship.
- **The evaluator fails closed.** Unparseable evaluator output counts as a failed round with a visible note. It is never a pass.
- **The evaluator is told it did not write the draft.** It is a small prompt detail that pushes against self-approval.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Rubber-stamp evaluator | Everything passes round 1; quality unchanged. | Calibrate against human labels; use a different model; include known-bad drafts in the eval set. |
| Infinite polishing | Rounds hit the budget on most tasks. | Budget; stall detection; check whether the rubric is satisfiable. |
| Oscillation | Fixing criterion A breaks B, and back again. | Revision prompt includes *all* outstanding feedback and the full rubric. |
| Vague feedback | "Improve tone." The generator changes random things. | Require one concrete, actionable fix per failed criterion. |
| Unsatisfiable task | Same feedback every round. | Stall detector → escalate (the Lee case). |
| Rubric gaming | Draft meets the letter of the rubric, misses its intent. | Add an intent criterion; review samples manually. |
| Cost blow-up | Evaluator re-checks mechanical criteria every round. | Move mechanical checks to code (exercise). |

## Variations

- **Best-of-N + evaluator.** Generate *N* drafts in [parallel (#3)](03-parallelization.md), evaluate all, pick the best. This trades rounds for breadth and gives lower latency at higher cost.
- **Scored rubric.** The evaluator returns per-criterion scores. Pass when all clear a threshold; keep the best-scoring draft if the budget runs out.
- **Tiered evaluators.** Cheap code checks first, then a cheap model, then an expensive model only for drafts that clear both.
- **Human as the evaluator, sometimes.** Sample some rounds for human review to keep the model evaluator calibrated. This is a bridge to [human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md).

## Try it

The rubric's "under 60 words" criterion is checkable in code. Put a free deterministic pre-check in front of the evaluator so over-long drafts are rejected **without spending an evaluator call**, and count the calls saved. You must not modify `optimize()`.

→ Solution: [Solutions — Evaluator–optimizer](../solutions/05-evaluator-optimizer.md)

## 60-second interview lens

- **Say:** "Evaluator–optimizer loops a generator and a separate rubric-driven evaluator: the evaluator returns specific fixes, the generator revises, and code stops the loop on pass, budget or stall."
- **Trade-off to name:** each round doubles calls and latency for gains that diminish fast; anything checkable in code should be a validator, not an evaluator criterion.
- **Expect the follow-up:** "How do you know the evaluator is any good?" Calibrate it against human labels on an eval set, and watch for an evaluator that passes everything.
- **Red flag to avoid:** looping until pass with no budget or stall detection.

## Related patterns

- [Reflection (#8)](../part-2-single-agent/08-reflection.md): the same model critiques itself. Cheaper, but it shares its own blind spots.
- [Guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md): deterministic validators instead of a judging model.
- [Critic–reviewer loop (#16)](../part-3-multi-agent/16-critic-reviewer.md): both sides are tool-using agents exchanging itemised findings over turns.
- [Eval harness (#21)](../part-4-cross-cutting/21-eval-harness.md): development-time measurement across many cases. Evaluator–optimizer improves one output at runtime.
