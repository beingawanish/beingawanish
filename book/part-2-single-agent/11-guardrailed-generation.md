# 11. Guardrailed generation (generate → validate → repair)

> **Intent.** Wrap a generation in deterministic validators. When output fails, send the model its own output plus the exact errors and ask for a repair; after a fixed repair budget, return a safe fallback and flag it, so invalid output never reaches users or downstream systems.

**Also known as:** validate-and-retry, output guardrails, structured-output repair · **Part:** 2 — Single-agent reasoning · **Code:** `code/patterns/guardrailed_generation/` *(canonical module, imported by the support-triage capstone)*

## Structure

![Guardrailed generation structure](../diagrams/guardrailed_generation.svg)

The model generates structured output. A list of validators, plain functions, checks schema and types, policy limits, PII and length. If all pass, the output goes on. If not, the errors go back to the model in a targeted repair prompt. After the repair budget is spent, a pre-written safe fallback is returned with `used_fallback=True`.

## Design concept & theory

**Core idea.** Some properties of an output are matters of judgement (is it kind?), and some are matters of fact (is it valid JSON? does it contain a card number? is the refund under the limit?). Facts should be checked by code: exactly, cheaply, every time. Models are good at *fixing* a specific error once it is pointed out.

**Why it works.**

- *Deterministic checks are cheap and exact.* A regex or a schema check costs microseconds and has no variance. A model asked "does this contain PII?" costs a call and is sometimes wrong. Anything checkable in code should be.
- *Targeted repair converges fast.* "Your previous output … failed: reply must not contain a card number" is far more actionable than regenerating from scratch. The model edits a nearly-right output instead of rolling the dice again.
- *A fallback bounds the worst case.* With repair budget *r* and per-attempt pass probability *p*, the chance of needing the fallback is *(1−p)^(r+1)*, and when it happens the output is still *safe*: a holding reply, flagged for a human. The system never ships invalid output; at worst it ships a known-safe one.
- *Validators are the spec.* A list of validators is an executable statement of what "valid" means, versioned with the code and unit-testable without any model.

**Invariants.** (1) Validators are deterministic code returning error messages. (2) Repairs include the failing output and the exact errors. (3) The repair budget is fixed. (4) Exhausting it yields a safe, flagged fallback, never the last invalid attempt.

**Lineage.** Design by contract (postconditions); input validation at trust boundaries; the retry-with-backoff loop, with feedback instead of backoff.

## When to use / when not to use

| Use it when | Don't use it when |
|---|---|
| Output feeds code (JSON, SQL, API calls) or a strict format. | The only "requirement" is subjective quality. Use an [evaluator (#5)](../part-1-workflow/05-evaluator-optimizer.md). |
| Business rules are mechanical (limits, allowed values, forbidden patterns). | You can constrain decoding directly (grammar or JSON mode) and that covers every rule. |
| Some outputs must never escape (PII, over-limit refunds). | There is no safe fallback and no one to escalate to. |
| You need an audit trail of what was rejected and why. | Validation needs knowledge only a model has. |

**Cheaper alternative:** constrained decoding or a provider's JSON mode, which guarantees *shape* for free. Add guardrailed generation for the rules shape cannot express: values, limits, PII, cross-field consistency.

## Forces & trade-offs

| Force | vs. unvalidated generation | Why |
|---|---|---|
| Latency | ↑ on failures only | Validators are ~free; each repair is one more call. |
| Cost | ↑ slightly | Repair calls, only for failing outputs. |
| Reliability | ↑↑ | Invalid output cannot pass; the worst case is a safe fallback. |
| Complexity | ↑ | Validators to write and test; fallback design; repair prompt. |

## Trade-off analysis & usage guidance

**Model.** With per-attempt pass rate *p* and repair budget *r*:

- Expected calls ≈ *1 + (1−p) + (1−p)² + … + (1−p)^r*. At *p* = 0.8 and *r* = 2 that is ≈ 1.24 calls.
- Fallback rate = *(1−p)^(r+1)*: 0.8% at *p* = 0.8, *r* = 2.
- Watch for *non-convergence*: if the same error repeats every attempt, more repairs will not help. Ticket #5120 in the example is exactly that.

**Decision checklist.**

1. List every rule the output must satisfy. Which can code check?
2. Is each validator's error message specific enough for a repair?
3. What is the safe fallback, and who sees flagged outputs?
4. What repair budget does your latency allow? Usually 1–2.
5. Are validators unit-tested on known-good and known-bad examples, including false positives (exercise)?

**Usage in production.**

- Log every rejection with the validator name. The rejection histogram tells you which prompt rule to improve.
- Alert on fallback rate. A jump means a model or prompt change broke something.
- Version validators with the prompt. A new rule without a prompt update causes fallback storms.
- Keep validators *pure* (no network). Checks that need lookups belong in the generation context, not the validator.

## Worked example

### Example first: what happens

```
python3 code/patterns/guardrailed_generation/main.py
```

<!-- expected-output: code/patterns/guardrailed_generation/main.py -->
```text
Guardrailed generation
======================
-- ticket #4471: double charge of $45
[attempt 1] INVALID: unparseable output: no JSON found in model output
[attempt 2] INVALID: reply must not contain a card number
[attempt 3] valid
result: ok=True attempts=3 reply='Refunded $45 to your card. Sorry for the trouble!'
-- ticket #5120: wants a full $180 refund
[attempt 1] INVALID: refund 180.0 exceeds the agent limit of 50.0
[attempt 2] INVALID: refund 180.0 exceeds the agent limit of 50.0
[attempt 3] INVALID: refund 180.0 exceeds the agent limit of 50.0
[fallback] {"reply": "Thanks for your patience — a teammate will review your case today.", "refund": 0.0, "tags": ["needs-human"]}
result: ok=False attempts=3 used_fallback=True tags=['needs-human']
```

**Ticket #4471:** attempt 1 is prose ("Sure! Here's a reply…"), not JSON, so the parse error becomes a validation error. Attempt 2 is valid JSON but echoes the customer's card number, and the PII validator rejects it. Attempt 3 is valid. Two repairs, each aimed at one exact failure.

**Ticket #5120:** the model offers a $180 refund three times against a $50 limit. It is not converging, so the safe fallback is returned with the tag `needs-human`. The customer gets a correct holding reply; the over-limit refund never leaves the system.

### Why first: why it is built this way

- **Validators are functions returning lists of strings.** They compose with `+`, can be unit-tested alone, and their messages go straight into the repair prompt. `require_fields`, `forbid_pattern`, `max_value`, `max_words` and `one_of` cover most needs; domain rules are three-line closures (the capstone adds `refund_within_order`).
- **Parse failure is a validation failure.** The model gets "unparseable output: no JSON found" like any other error, and one code path handles all failures.
- **The repair prompt repeats the original request.** The model must still satisfy everything, not just the flagged rule. Otherwise fixing one error tends to break another.
- **The fallback is data you wrote.** It is never "the last attempt, but flagged". Invalid output is not shipped, even with a warning.
- **`GuardResult.errors` keeps every attempt's errors.** That is the audit trail, and the input to the rejection dashboard.

## Failure modes & guardrails

| Failure mode | Symptom | Guardrail |
|---|---|---|
| Non-converging repairs | Same error every attempt. | Fixed budget, then fallback; consider stall detection like [#5](../part-1-workflow/05-evaluator-optimizer.md). |
| False-positive validator | Valid output rejected (an order number flagged as a card). | Precise rules (Luhn check, exercise); test validators on real samples. |
| Whack-a-mole | Fixing A breaks B. | Repair prompt includes the full request and *all* current errors. |
| Fallback overuse | Many users get holding replies. | Monitor the fallback rate; fix the root prompt or rule. |
| Validator drift | Rules change; the prompt does not mention them. | Version prompt and validators together; generate rule text from the validators. |
| Over-trusting validity | Valid but wrong content passes. | Validity ≠ correctness: add evaluation or review where content matters. |

## Variations

- **Constrained decoding first.** Use a grammar or JSON schema at decode time for shape, and validators for semantics.
- **Validator-generated instructions.** Render the rule list into the generation prompt from the same validator objects, so the prompt cannot drift from the checks.
- **Partial repair.** For large outputs, re-generate only the failing field or section.
- **Fail closed to a human.** Instead of a canned fallback, route to [human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md). The support-triage capstone does both.

## Try it

The `CARD_NUMBER` regex blocks any 13–16 digit run, so a reply quoting a 16-digit *order* number is rejected and repaired for nothing. Add a **Luhn checksum** so only digit runs that could be real card numbers are blocked. Show the order number passing and a test card still blocked.

→ Solution: [Solutions — Guardrailed generation](../solutions/11-guardrailed-generation.md)

## 60-second interview lens

- **Say:** "Guardrailed generation wraps a model call in deterministic validators. Failures go back to the model with the exact errors for a targeted repair, and after a fixed budget a safe fallback is returned and flagged."
- **Trade-off to name:** a little extra latency on failing outputs buys a hard guarantee that invalid output never ships. The catch is validator quality, especially false positives.
- **Expect the follow-up:** "Why not just use JSON mode?" JSON mode guarantees shape. It cannot enforce refund limits, PII rules or cross-field consistency.
- **Red flag to avoid:** returning the last invalid attempt "with a warning" when the budget runs out.

## Related patterns

- [Evaluator–optimizer (#5)](../part-1-workflow/05-evaluator-optimizer.md): the same loop with an LLM judge for qualities code cannot check.
- [Prompt chaining (#1)](../part-1-workflow/01-prompt-chaining.md): gates between steps are validators without the repair.
- [Human-in-the-loop (#17)](../part-3-multi-agent/17-human-in-the-loop.md): where flagged fallbacks should go.
- [Support-triage capstone](../capstones/support-triage.md): this module in production-shaped use.
