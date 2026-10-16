# Capstone 1 — Support triage system

> **Composes:** [Routing (#2)](../part-1-workflow/02-routing.md) · [Parallelization (#3)](../part-1-workflow/03-parallelization.md) · [Guardrailed generation (#11)](../part-2-single-agent/11-guardrailed-generation.md) · [Human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md) · [Eval harness (#21)](../part-4-cross-cutting/21-eval-harness.md)
> **Code:** `code/capstones/support_triage/` · **Run:** `python3 code/capstones/support_triage/main.py`

The capstones are where patterns stop being diagrams. This one is deliberately *workflow-shaped*: no step lets a model choose what happens next. Every decision about control flow — which handler, whether to repair, whether a human must look — is made by code, using model outputs as inputs. That is what makes the system testable against a written spec.

## 1. The brief (written first)

The full brief is in `code/capstones/support_triage/brief.md`. In short:

| ID | Requirement | Pattern |
|---|---|---|
| R1 | Look up the customer, classify sentiment and search the KB **concurrently**; a failed lookup must not block the others. | Parallelization |
| R2 | Exactly one route from `billing / technical / account / general`; unambiguous tickets cost no LLM call; low-confidence or invalid answers go to `general`. | Routing |
| R3 | JSON reply `{reply, refund}` that passes schema, no card numbers, ≤ 60 words, refund ≤ order total; ≤ 2 repairs then a safe holding reply. | Guardrailed generation |
| R4 | Human approval before sending when: refund > $50; VIP *and* angry; route fell back; or guardrail fallback used. Survives restart; never sends twice. | Human-in-the-loop |
| R5 | A fixed eval set and one command reporting route accuracy, escalation accuracy, PII safety and reply quality. | Eval harness |

**Acceptance criteria:** route accuracy ≥ 0.85 · escalation accuracy = 1.00 · PII safety = 1.00 · reply quality ≥ 0.80.

The expected route and status for each of the eight eval tickets were written from the brief *before* the solution existed, including one ticket (TK-104) where the honest expectation is that the system will *not* get the route right.

## 2. Architecture

![Support triage architecture](../diagrams/support_triage.svg)

The capstone owns only three files:

- `triage.py`: the glue (about 100 lines). It imports `Router`, `fan_out`, `guarded_generate`, the validators, `Policy`, `ReviewQueue` and `submit_or_execute`, and re-implements none of them.
- `fixtures.py`: everything that would be "the outside world": mock CRM, mock KB, the eval set, the mock model, and a *separate* judge model.
- `main.py`: one traced walkthrough, then the eval and the acceptance check.

## 3. Example first: one ticket, end to end

TK-108 is the hardest ticket: the customer pasted their card number into the message.

<!-- expected-output: code/capstones/support_triage/main.py -->
```text
Support triage capstone
=======================
-- walkthrough: TK-108 (card number in the ticket)
[enrich] customer={'tier': 'standard', 'order_total': 30} sentiment=neutral kb='Duplicate charges and refunds'
[route] billing via keyword (1.00) unique keyword match
[attempt 1] INVALID: reply must not contain a card number
[attempt 2] valid
[decide] sent
-- eval
[TK-101] billing   sent    refund=29
[TK-102] technical sent    refund=0
[TK-103] billing   pending refund=240
[TK-104] general   pending refund=0
[TK-105] account   sent    refund=0
[TK-106] billing   pending refund=0
[TK-107] technical sent    refund=0
[TK-108] billing   sent    refund=15
support-triage v1:
  route_correct    0.88  [critical] 1.00  fails: TK-104
  status_correct   1.00  [critical] 1.00  fails: -
  pii_safe         1.00  [critical] 1.00  fails: -
  quality          0.86  [critical] 0.80  fails: TK-106
auto-send rate: 5/8; outbox=5; pending review: R001, R002, R003
model usage: 23 calls, 1002 in / 292 out tokens, $0.0074
-- acceptance
[PASS] route_correct 0.88 (>= 0.85)
[PASS] status_correct 1.00 (>= 1.00)
[PASS] pii_safe 1.00 (>= 1.00)
[PASS] quality 0.86 (>= 0.80)
```

The first block is the walkthrough. Enrichment ran three branches concurrently. Routing was free (the unique keyword "charged"). The first draft echoed the card number back to the customer, the PII validator rejected it, and the targeted repair produced a reply mentioning only the last four digits. The $15 refund is under the $50 review threshold, so it was sent automatically.

The second block is the eval over all eight tickets:

- **TK-103** (VIP, angry, $240 refund) is held for review, for two separate reasons.
- **TK-104** (*"How do I export my data?"*) is routed `general`. The classifier said `account` at 0.62, below the 0.7 threshold, so it fell back, and the fallback rule held it for review. The route is "wrong" by the eval's truth label, and the system still did the right thing. That is the one route miss (0.88 ≥ 0.85).
- **TK-105**: the CRM lookup *failed* (customer c5 does not exist). The other two branches still completed, triage continued with `tier=unknown`, and the prose-not-JSON first draft was repaired.
- **TK-106**: the model kept offering a $900 refund on a $60 order. Three attempts failed the `refund ≤ order total` validator, the safe holding reply was used, and the guardrail-fallback rule held it for review. The judge scored this generic reply 0.6, its only quality failure.

All four acceptance criteria pass, and `verify.py` re-checks them on every run.

## 4. Why first: the design decisions

**Concurrency only where it is free.** Enrichment branches are independent, so they fan out. Routing, drafting and the policy decision depend on each other, so they are sequential. Parallelization (#3) is a tool for independent work, not a default.

**Two thresholds, two jobs.** The guardrail's refund check (≤ order total) is a *validity* rule: a reply that violates it is wrong and must never be sent. The policy's $50 rule is a *risk* rule: the reply may be right, but a person should see it first. Keeping them in different patterns (#11 vs #17) keeps each one simple and independently testable.

**Policy is built per ticket, from context.** The escalation rules depend on things the action itself does not carry: the customer's tier, the sentiment, how the route was chosen, whether the guardrail fell back. `escalation_policy()` closes over that context. The model never decides its own oversight.

**Fail toward a person, never toward silence.** Every degraded path (unknown route, guardrail fallback, failed lookup) still produces a reply. When the system is unsure, that reply is held for a human rather than sent.

**The judge is a different model.** The quality scorer uses `make_judge()`, not the model that wrote the replies. An earlier draft of this capstone used the same model for both; reviewing the first run exposed it. Self-grading inflates scores; see the [eval harness chapter](../part-4-cross-cutting/21-eval-harness.md).

**Graded scorers need a pass mark.** Reply quality is a 0–1 score. Counting every score below 1.0 as a failure made the report list all eight tickets as "failing". The harness now carries a per-scorer `pass_mark` (0.7 for the judge), so `fails: TK-106` points at the one reply that needs attention.

## 5. Cost and latency

From the run: **23 model calls for 8 tickets** (plus 8 judge calls at eval time only). Per ticket that is 1 sentiment call + 0–1 classifier calls + 1–3 draft attempts. The illustrative cost model:

- Happy path (keyword route, first draft valid): 2 calls, with latency ≈ max(enrichment) + draft.
- Worst path (LLM route, full repair budget): 5 calls.
- The keyword pre-filter resolved 5 of 8 tickets, and the eval quantifies that saving.

## 6. Extending it (exercises for the reader)

1. Add a `security` route whose handler *always* requires review, and add two eval cases for it, one tagged `critical`.
2. Run the eval with the routing threshold at 0.6 and at 0.8, and use `compare()` to decide which to ship.
3. Simulate a restart between `submit` and the reviewer's decision (see the [human-in-the-loop](../part-3-multi-agent/17-human-in-the-loop.md) example) and confirm no reply is sent twice.
