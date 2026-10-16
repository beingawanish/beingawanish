# Capstone brief — Support triage system

*Spec first. This brief was written before the solution; the solution is judged against it.*

## Problem

Acme's support inbox receives free-text tickets. Today every ticket is read by a person.
Build a triage system that drafts a correct, safe reply for every ticket, sends the routine
ones automatically, and puts the risky ones in front of a human — and that can *prove*,
with an offline eval, that it does so.

## Inputs and outputs

- **Input:** a ticket `{id, customer_id, text}`.
- **Tools available:** `crm.lookup(customer_id)` → tier, order total; `kb.search(query)` → best help article.
- **Output:** `TriageOutcome {ticket_id, route, sentiment, reply, refund, status, reasons, request_id}`,
  where `status ∈ {sent, pending}`.

## Requirements

| ID | Requirement | Pattern |
|----|-------------|---------|
| R1 | Look up the customer, classify sentiment, and search the KB **concurrently**; a failed lookup must not block the others. | Parallelization (#3) |
| R2 | Assign exactly one route from `billing, technical, account, general`; unambiguous tickets must not cost an LLM call; low-confidence or invalid classifications go to `general`. | Routing (#2) |
| R3 | Draft replies as JSON `{reply, refund}` that pass deterministic checks: schema, no card numbers, ≤ 60 words, refund ≤ the customer's order total. Repair at most twice, then fall back to a safe holding reply. | Guardrailed generation (#11) |
| R4 | A human must approve before sending when: refund > $50; customer is VIP **and** sentiment is angry; route fell back to `general`; or the guardrail fallback was used. Approval state must survive a restart; nothing is sent twice. | Human-in-the-loop (#17) |
| R5 | Ship a fixed eval set and a single command that reports route accuracy, escalation accuracy, PII safety and reply quality. | Eval harness (#21) |

## Acceptance criteria (checked by `main.py`, enforced by `verify.py`)

| Metric | Threshold |
|--------|-----------|
| Route accuracy | ≥ 0.85 |
| Escalation accuracy (sent vs pending) | = 1.00 — every risky ticket held, no safe ticket held |
| PII safety (no card numbers in any reply) | = 1.00 |
| Reply quality (LLM judge, mean) | ≥ 0.80 |
| Auto-send rate | reported (not gated) |

## Non-goals

Multi-turn conversations, real email delivery, real CRM integration, and model fine-tuning.

## Composition (no duplicate implementations)

The solution **imports** `patterns.routing.router`, `patterns.parallelization.fanout`,
`patterns.guardrailed_generation.guardrails`, `patterns.human_in_the_loop.hitl` and
`patterns.eval_harness.harness`. The capstone owns only the glue (`triage.py`), the fixtures
(`fixtures.py`), and the eval set.

## Run

```
python3 code/capstones/support_triage/main.py
```
