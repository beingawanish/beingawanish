# Capstone 2 — Deep-research agent

> **Composes:** [Plan-and-execute (#7)](../part-2-single-agent/07-plan-and-execute.md) · [Agentic RAG (#10)](../part-2-single-agent/10-agentic-rag.md) · [Reflection (#8)](../part-2-single-agent/08-reflection.md) · [Evaluator–optimizer (#5)](../part-1-workflow/05-evaluator-optimizer.md) · [Memory tiers (#19)](../part-4-cross-cutting/19-memory-tiers.md)
> **Code:** `code/capstones/deep_research/` · **Run:** `python3 code/capstones/deep_research/main.py`

The support-triage capstone was a workflow: code decided every step. This one is an *agent*: a planner decides which sub-questions to research, a retrieval agent decides how to search, and the plan changes when the sources run dry. What keeps it trustworthy is that every claim must trace to a retrieved source, and code, not the model, checks that.

## 1. The brief (written first)

The full brief is in `code/capstones/deep_research/brief.md`. The question is *"Should we move our 500 GB Postgres to the managed service? Cover cost, migration downtime, compliance and lock-in."*

| ID | Requirement | Pattern |
|---|---|---|
| R1 | Explicit plan of sub-questions; re-plan when one cannot be answered. | Plan-and-execute |
| R2 | Each sub-question answered by query → grade → reformulate → cite, or abstain. | Agentic RAG |
| R3 | Recall findings from long-term memory before researching; store new findings with provenance. | Memory tiers |
| R4 | The writer critiques its own draft for unsupported claims. | Reflection |
| R5 | A separate evaluator holds the report to a rubric within a round budget. | Evaluator–optimizer |

**Acceptance criteria:** 4/4 topics covered with citations · every number cited and every cited id real · zero unsupported claims in the final report · evaluator pass within 3 rounds · a follow-up question on known topics makes **zero** retrieval-agent calls.

## 2. Architecture

![Deep-research architecture](../diagrams/deep_research.svg)

`research.py` is about 120 lines of glue. One plan step is "recall from memory, else research with agentic RAG and store the finding". After the plan completes, the writer reflects on its own draft, and a separate evaluator drives rubric revisions through `optimize()`. All five patterns are imported unchanged; the only adapter is a ten-line wrapper that lets `optimize()` start from the reflected draft instead of writing a new one.

## 3. Example first: the run

<!-- expected-output: code/capstones/deep_research/main.py -->
```text
Deep-research capstone
======================
-- session 1: Should we move our 500 GB Postgres to the managed service? Cover cost, migration downtime, compliance and lock-in.
[plan v1] q1:research → q2:research → q3:research → q4:research
[query 1] 'managed postgres month cost self-managed' -> ['src-pricing', 'src-compliance']
[grade] relevant=['src-pricing'] sufficient=True
[answer] Managed costs about $1,450/month vs about $900/month self-managed plus an estimated 10 engineer-hours/month o…
[exec q1] ok  Managed costs about $1,450/month vs about $900/month self-managed plus an estimated 10 engineer-hours/mon…
[query 1] 'migration cutover downtime logical replication' -> ['src-migration', 'src-portability']
[grade] relevant=['src-migration'] sufficient=True
[answer] Logical-replication cutover needs about 5-15 minutes of write downtime; dump-and-restore of 500 GB takes hour…
[exec q2] ok  Logical-replication cutover needs about 5-15 minutes of write downtime; dump-and-restore of 500 GB takes…
[query 1] 'EU region residency SOC certified' -> ['src-compliance']
[grade] relevant=['src-compliance'] sufficient=True
[answer] EU-region hosting, SOC 2 Type II and ISO 27001 certified; residency can be pinned to eu-west [src-compliance].
[exec q3] ok  EU-region hosting, SOC 2 Type II and ISO 27001 certified; residency can be pinned to eu-west [src-complia…
[query 1] 'vendor lock-in exit fee' -> no hits
[query 2] 'contract termination penalty' -> no hits
[abstain] I couldn't find this in our documentation, so I won't guess. A specialist can confirm.
[exec q4] FAIL None (no sources for 'What exit fees or contract lock-in apply?')
[plan v2] q5:research
[query 1] 'leaving export pg_dump replication' -> ['src-portability', 'src-migration']
[grade] relevant=['src-portability'] sufficient=True
[answer] Leaving uses standard pg_dump or logical replication out, the same tools as arriving [src-portability].
[exec q5] ok  Leaving uses standard pg_dump or logical replication out, the same tools as arriving [src-portability].
[draft] Recommendation: move, using logical replication and a scheduled cutover window. Cost: managed runs about $1,4…
[critique 1] Overclaim: 'near-zero downtime' is not in the findings, which say about 5-15 minutes of write downtime [src-m…
[revision 1] Recommendation: move, using logical replication and a scheduled cutover window. Cost: managed runs about $1,4…
[round 1 draft] Recommendation: move, using logical replication and a scheduled cutover window. Cost: managed runs about $1,4…
[round 1 eval] FAIL: State that the operations-hours figure is a vendor estimate we have not measured
[round 2 draft] Recommendation: move, using logical replication and a scheduled cutover window. Cost: managed runs about $1,4…
[round 2 eval] PASS
-- final report
Recommendation: move, using logical replication and a scheduled cutover window. Cost: managed runs about $1,450/month versus about $900/month self-managed plus an estimated 10 engineer-hours/month of operations [src-pricing]. Downtime: plan for 5-15 minutes of write downtime at cutover with logical replication; dump-and-restore would take hours [src-migration]. Compliance: EU-region hosting with SOC 2 Type II and ISO 27001, pinned to eu-west [src-compliance]. Lock-in: low, because leaving uses pg_dump or logical replication, the same tools as arriving [src-portability]. Uncertainty: the operations-hours figure is the vendor's estimate, not our measurement; check it against our on-call logs.
-- session 2 (new process): For the Postgres move, what downtime and cost should we expect?
[plan v1] q2:research → q1:research
[exec q2] ok  Logical-replication cutover needs about 5-15 minutes of write downtime; dump-and-restore of 500 GB takes…
[exec q1] ok  Managed costs about $1,450/month vs about $900/month self-managed plus an estimated 10 engineer-hours/mon…
[draft] Downtime: plan for 5-15 minutes of write downtime at cutover with logical replication; dump-and-restore would…
[critique 1] NO ISSUES
[round 1 draft] Downtime: plan for 5-15 minutes of write downtime at cutover with logical replication; dump-and-restore would…
[round 1 eval] PASS
-- acceptance
session 1: plan versions=2, retrieval-agent calls=14
[PASS] coverage: 4/4 topics cited
[PASS] citation integrity: 0 problems
[PASS] unsupported claims: 'near-zero' removed
[PASS] evaluator: passed=True in 2 round(s)
[PASS] follow-up from memory: retrieval-agent calls=0, memory hits=['downtime', 'cost']
```

Read it as four acts:

1. **Research.** Plan v1 has four sub-questions. Cost, downtime and compliance each take one query: retrieve, grade, cite. The lock-in sub-question asks about *exit fees*. Two queries find nothing, the retrieval agent abstains, and the step fails.
2. **Re-plan.** The planner sees the failure and replaces the dead sub-question with one the sources *can* answer: data portability. Plan v2 has one step, and it succeeds. This is plan-and-execute doing its job: the goal (cover lock-in) survived the failure of one route to it.
3. **Write.** The first draft claims "near-zero downtime", which no finding supports. Reflection catches it, since the critique compares the draft with the findings, and the revision cites the 5–15 minutes from `src-migration`. The evaluator then asks for one more thing the rubric requires: say that the operations-hours figure is a vendor estimate. Round 2 passes.
4. **Remember.** Session 2 is a new process with the same memory file. Its follow-up question plans two sub-questions, both are memory hits, and the retrieval agent is never called.

## 4. Why first: the design decisions

**Memory sits inside the plan step, not around the agent.** Recall happens per sub-question (`finding:<topic>`), so a follow-up that overlaps partly with earlier research reuses exactly the overlap and researches the rest. Storing whole reports would make reuse all-or-nothing.

**Abstention is what makes re-planning possible.** If the retrieval agent had guessed an answer about exit fees, the step would have "succeeded" and the report would contain an invented claim. Because it abstained, the failure was visible, and the planner could route around it.

**Two reviewers, in cost order.** Reflection is cheap (same model, no rubric) and catches the obvious overclaim. The evaluator is more expensive and independent, and catches what the writer does not see as a problem (missing uncertainty). Running the cheap check first means the expensive one starts from a better draft.

**Code has the last word.** `citation_problems()` checks that every sentence with a number cites a source and that every cited id exists. Coverage is checked by looking for each topic's source id in the report. Neither check trusts the evaluator's verdict.

**One retrieval model, one counter.** `CountingLLM` wraps only the retrieval agent's model, so "0 calls in session 2" is a measurement, not a claim.

## 5. Cost and latency

From the run: session 1 makes 14 retrieval-agent calls (four answered sub-questions at query + grade + answer, plus two unanswered queries), 2 planner calls, 4 writer calls and 2 evaluator calls. Session 2 makes 1 planner call, 2 writer calls, 1 evaluator call and **0** retrieval calls.

The illustrative economics: retrieval and grading run on the small model (priced at a twelfth of the planner's input rate in the fixtures), so the expensive model is used only to plan and write. Memory turns repeated research into lookups. The more a team asks about the same system, the cheaper each question gets.

## 6. Extending it

1. Add a `src-sla` document and a fifth topic ("availability SLA"). Confirm the planner's sub-question is answered and the coverage check now expects 5/5.
2. Make findings expire: store a `researched_at` session and treat findings older than *N* sessions as misses ([memory tiers, #19](../part-4-cross-cutting/19-memory-tiers.md)).
3. Replace the evaluator's single verdict with the [eval harness (#21)](../part-4-cross-cutting/21-eval-harness.md) over five research questions, and compare runs with and without the reflection step.
