# Capstone brief — Deep-research agent

*Spec first. This brief was written before the solution; the solution is judged against it.*

## Problem

An engineering lead asks a decision question that needs several facts from a document
collection: *"Should we move our 500 GB Postgres to the managed service? Cover cost,
migration downtime, compliance and lock-in."* Build an agent that researches it,
writes a short cited recommendation, refuses to claim what the sources do not say,
and remembers what it learned, so that a follow-up question in a later session does
not redo the research.

## Inputs and outputs

- **Input:** a question; a corpus of source documents `{id: text}`; a memory file path.
- **Output:** `ResearchReport {question, findings{topic: text}, report, plan_versions, rag_calls, eval}`.

## Requirements

| ID | Requirement | Pattern |
|----|-------------|---------|
| R1 | Decompose the question into sub-questions with an explicit plan; when a sub-question cannot be answered from the sources, re-plan instead of failing or guessing. | Plan-and-execute (#7) |
| R2 | Answer each sub-question by deciding queries, grading retrieved passages, reformulating, and citing only retrieved sources. Abstain when evidence is insufficient. | Agentic RAG (#10) |
| R3 | Before researching a sub-question, recall it from long-term memory; store every new finding with provenance. Memory survives a restart. | Memory tiers (#19) |
| R4 | The writer critiques its own draft for claims the findings do not support, and revises. | Reflection (#8) |
| R5 | A separate evaluator checks the report against a rubric (cited claims, full coverage, stated uncertainty, length) and drives revisions within a budget. | Evaluator–optimizer (#5) |

## Acceptance criteria (checked by `main.py`, enforced by `verify.py`)

| Metric | Threshold |
|--------|-----------|
| Coverage — every requested topic has a cited finding in the report | 4 / 4 |
| Citation integrity — every sentence with a number cites a source, and every cited id exists in the corpus | 100% |
| Unsupported claims surviving to the final report | 0 |
| Evaluator verdict | pass within ≤ 3 rounds |
| Follow-up session on already-researched topics | 0 retrieval-agent model calls |

## Non-goals

Web search, PDF parsing, ranking models, multi-user memory.

## Composition (no duplicate implementations)

Imports `patterns.plan_and_execute.planner`, `patterns.agentic_rag.rag`,
`patterns.reflection.reflect`, `patterns.evaluator_optimizer.optimizer` and
`patterns.memory_tiers.memory`. The capstone owns only `research.py` (glue),
`fixtures.py` (corpus and mock models) and `main.py`.

## Run

```
python3 code/capstones/deep_research/main.py
```
