# 3. Parallelization (fan-out / fan-in)

> **Intent.** Run several independent model calls at the same time — different subtasks of one input (*sectioning*) or the same task several times (*voting*) — and combine their results in code.

**Also known as:** scatter-gather, fan-out/fan-in, map-reduce, self-consistency (voting variant) · **Part:** 1 — Workflow · **Code:** `code/patterns/parallelization/`

## Structure

![Parallelization structure](../diagrams/parallelization.svg)

Code fans a draft reply out to three independent checks that run concurrently. A code fan-in step aggregates their verdicts. Here it *fails closed*: one failing branch, or one branch that crashed, blocks the draft. In the voting variant every branch gets the same prompt, and the fan-in takes a majority, subject to a quorum.

## Design concept & theory

**Core idea.** If two pieces of work do not depend on each other, there is no reason to wait for one before starting the other. And if one model answer is noisy, several answers combined are less noisy, *provided their errors are not all the same error*.

**Why it works: two separate mechanisms.**

1. *Sectioning buys latency and focus.* Sequential checks take *Σ tᵢ*; parallel ones take *max tᵢ* (plus overhead). Separately, each branch has a single concern: a tone checker that is not also checking refund policy pays full attention to tone. That is the same narrowing benefit as chaining, without the sequential penalty.
2. *Voting buys reliability, under an independence assumption.* If each of three voters is right with probability *p* = 0.8 *and their errors are independent*, the majority is right with probability 3p²(1−p) + p³ ≈ **0.896** (Condorcet's jury theorem). The catch is the condition: three samples from the same model on the same prompt make *correlated* errors. If the model misreads the input, it usually misreads it every time. Voting helps against *random* slips (a flipped label, a sampling accident), and helps little against *systematic* misunderstanding. Diversify prompts, models or input order to decorrelate the voters.

**Invariants.** (1) The split is known *before* runtime; code, not a model, decides the branches. (2) Branches do not communicate. (3) Aggregation is done in code, with an explicit rule for failed branches.

**Lineage.** *Scatter-Gather* and *Aggregator* (Enterprise Integration Patterns); *fork-join* in concurrent programming; *MapReduce* when the split is over data. The voting variant is ensemble learning applied at inference time.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| Subtasks are independent and you know them in advance (several guardrail checks, several documents). | Each step needs the previous step's output ([chain it, #1](01-prompt-chaining.md)). |
| Latency matters and calls are I/O-bound. | The split depends on the input's content (use [orchestrator–workers, #4](04-orchestrator-workers.md)). |
| A single answer is too noisy and errors look random (vote). | Errors are systematic. Voting the same mistake three times does not fix it. |
| Rate limits allow the extra concurrent calls. | Cost is the binding constraint and one good call suffices. |

**Cheaper alternative:** do all checks in *one* call ("check tone, policy and facts; return three verdicts"), or run them sequentially. Upgrade when the combined prompt's checks interfere with each other, or when latency is the bottleneck.

## Forces & trade-offs

| Force | vs. one combined call / sequential calls | Why |
|---|---|---|
| Latency | ↓ better than sequential | Wall time ≈ slowest branch, not the sum. |
| Cost | ↑ | *N* calls instead of one; voting multiplies cost by the number of voters. |
| Reliability | ↑ | Focused branches (sectioning); averaged noise (voting, if errors are independent). |
| Complexity | ↑ moderately | Concurrency, partial failures, an aggregation rule, rate limits. |

## Trade-off analysis & usage guidance

**Model.** For *N* branches with latencies *tᵢ* and costs *cᵢ*:

- Latency ≈ *max tᵢ + overhead* (bounded by your concurrency limit: with *W* workers, ≈ ⌈N/W⌉ waves).
- Cost = *Σ cᵢ*: parallelism saves time, never money.
- Voting with *k* voters: cost ×*k*. The reliability gain shrinks as voter correlation rises, and is roughly zero for perfectly correlated voters.

**Aggregation rules (choose deliberately).**

| Rule | Use for | Failed branch counts as |
|---|---|---|
| All must pass | guardrails, safety | fail (closed) |
| Any passes | recall-oriented search | ignored |
| Majority with quorum | classification votes | not a vote; may break quorum |
| Merge / concatenate | sectioned content | gap flagged in output |

**Decision checklist.**

1. Are the branches truly independent (no branch needs another's output)?
2. Is the aggregation rule written down, *including what a crashed branch means*?
3. Do rate limits and concurrency limits allow *N* simultaneous calls?
4. For voting: what makes your voters' errors *different* from each other?
5. Is the latency saving worth *N*× the calls?

**Usage in production.**

- Give every branch a timeout. One slow branch sets your latency.
- Return results in a stable order (input order, not completion order) so logs and tests are deterministic. `fan_out` does this.
- Record per-branch outcomes, not just the aggregate. "Policy check fails 12% of drafts" is actionable; "drafts fail 15%" is not.
- Use a bounded worker pool. Unbounded fan-out against a rate-limited API turns into retries and gets slower.

## Worked example

### Example first: what happens

```
python3 code/patterns/parallelization/main.py
```

<!-- expected-output: code/patterns/parallelization/main.py -->
```text
Parallelization
===============
-- sectioning: three independent guardrail checks on a draft reply
[check:tone] pass=True — warm and professional
[check:policy] pass=False — promises a refund above the $50 agent limit
[check:facts] pass=True — order number and dates match the record
[fan-in] approved=False
[timing] parallel faster than sequential: True
-- voting: three judges on one email
[judge:A] PHISHING
[judge:B] PHISHING
[judge:C] discarded ("I'm not sure, it could be either.")
[fan-in] verdict=PHISHING agreement=1.00 from 2 usable votes
```

*Sectioning.* Three checks (tone, policy, facts) run concurrently on the same draft. The mock adds 0.15 s of simulated latency per call, and the run asserts that wall time beat the sequential sum. Policy fails (a $120 refund exceeds the $50 limit), so the fail-closed fan-in blocks the draft, even though two of three checks passed.

*Voting.* Three judges classify a suspicious email. Judge C's answer is unusable and is discarded rather than counted. The verdict is PHISHING. But look at the last line: *"agreement=1.00 from 2 usable votes"*. That number overstates the evidence, and the exercise fixes it.

### Why first: why it is built this way

- **Branches never raise.** `fan_out` catches every exception and returns a `Branch` with either a value or an error. One branch's failure is data for the aggregator, never a crash that kills its siblings.
- **The aggregator owns the semantics.** `fan_out` does not know whether a failure should block (guardrails) or be ignored (search). That choice lives in the caller, in one visible line: `all(b.ok and b.value["pass"] for b in branches)`.
- **Unparseable votes are not votes.** Counting "I'm not sure" as a vote for either side would be invented evidence. Discarding it is correct, but then *agreement* must be reported against votes cast, not votes kept.
- **Input-order results.** Branch results come back in the order they were submitted, so the trace is identical on every run even though completion order is not.
- **Reuse.** [Orchestrator–workers (#4)](04-orchestrator-workers.md) and the [support-triage capstone](../capstones/support-triage.md) import this exact `fan_out`. There is one implementation of concurrency in the codebase.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Correlated voters | Votes agree and are all wrong. | Diversify prompts, models or example order; measure inter-voter agreement on an eval set. |
| Silent partial failure | A crashed branch is treated as a pass. | Explicit per-rule semantics; fail closed for safety checks. |
| Quorum collapse | Verdict from 1–2 usable votes looks confident. | Require a quorum; report agreement against votes cast. |
| Rate-limit storm | Fan-out triggers 429s, then retries, then slower than sequential. | Bounded pool; exponential backoff; per-provider concurrency limits. |
| Tail latency | One slow branch dominates. | Per-branch timeout; treat a timeout as a failed branch under the aggregation rule. |
| Merge conflicts (sectioning) | Two branches produce contradictory content. | Make sections disjoint; or add a final reconciliation call, and accept that this makes it a small chain. |

## Variations

- **Self-consistency.** Sample several reasoning paths for one question and vote on the final answer. This is the voting variant applied to chain-of-thought.
- **Best-of-N with a scorer.** Generate *N* candidates in parallel and pick the best with a deterministic scorer or a judge. This is the step before [evaluator–optimizer (#5)](05-evaluator-optimizer.md) iterates.
- **Map-reduce over documents.** Sectioning by data: summarise each chunk in parallel, then reduce.
- **Hedged requests.** Send the same request to two providers and take the first good answer. Parallelism used for tail latency, not quality.
- **Guardrail fan-out.** Run safety and policy checks *in parallel with* generation, and cancel or withhold the output if a check fails.

## Try it

In the voting run, judge C's vote was unusable, yet the verdict was reported with "agreement 1.00". Add a **quorum**: require at least three usable votes or return no verdict (escalate). Report agreement against votes *cast*, not votes kept. Show both the no-quorum case and a three-vote case.

→ Solution: [Solutions — Parallelization](../solutions/03-parallelization.md)

## 60-second interview lens

- **Say:** "Parallelization runs independent calls concurrently and aggregates in code: sectioning splits one task into independent checks; voting repeats one task to reduce noise."
- **Trade-off to name:** it saves wall-clock time, never money, and voting only helps if the voters' errors are independent.
- **Expect the follow-up:** "What happens when one branch fails?" Answer: that is a design decision. Fail closed for safety checks, ignore for recall-oriented search, and break quorum for votes. Never let it crash the others.
- **Red flag to avoid:** claiming three samples from the same model at the same temperature are three independent opinions.

## Related patterns

- [Orchestrator–workers (#4)](04-orchestrator-workers.md): the split is decided by a model at runtime, not by code in advance.
- [Swarm (#18)](../part-3-multi-agent/18-swarm.md): agents interact and the workload is emergent. Parallel branches never talk to each other.
- [Debate (#15)](../part-3-multi-agent/15-debate.md): voters that *see and respond to* each other's arguments over rounds.
- [Guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md): deterministic checks are cheaper than LLM-judged branches; use them first.
