# Chapter template (pilot draft — not locked until approved at Gate 2)

Every pattern chapter uses these sections, in this order, with these exact headings.
Section 3 (design concept & theory) and section 6 (trade-off analysis & usage guidance) were added at your request during the pilot.

```markdown
# <N>. <Pattern name>

> **Intent.** <one sentence>

**Also known as:** … · **Part:** … · **Code:** `code/patterns/<slug>/`

## Structure
![<Pattern> structure](../diagrams/<slug>.svg)
<one-paragraph caption: what each box is; colour key>

## Design concept & theory
- Core idea: the mechanism in plain words.
- Why it works: the underlying reasoning (e.g. error compounding, independence of votes,
  separation of concerns), with a back-of-envelope formula where one exists.
- Invariants: what must stay true for the pattern to be this pattern.
- Lineage: the closest classic software or systems pattern (GoF, EIP, distributed systems).

## When to use / when not to use
| Use it when | Don't use it when |
- **Cheaper alternative:** <named pattern or technique>, and the signal that you need to upgrade.

## Forces & trade-offs
| Force | vs. <cheaper alternative> | Why |
Rows: latency · cost · reliability · complexity (each rated ↑ / ↓ / ≈).

## Trade-off analysis & usage guidance
- Cost/latency model: formulas in terms of calls, tokens, rounds, fan-out.
- Decision checklist: 4–6 yes/no questions.
- Usage in production: defaults, budgets, what to log, what to alert on.

## Worked example
### Example first — what happens
Walkthrough of the companion run, quoting the verified output.
### Why first — why it is built this way
The design decisions, each tied to a force or failure mode.

## Failure modes & guardrails
| Failure mode | Symptom | Guardrail |

## Variations
Named variants, one paragraph each.

## Try it
Exercise statement. → Solution: `book/solutions/<slug>.md` (code in `exercise_solution.py`, verified).

## 60-second interview lens
- **Say:** … · **Trade-off to name:** … · **Expect the follow-up:** … · **Red flag to avoid:** …

## Related patterns
Cross-links with the one-line distinction from the scope sheet.
```

## Conventions

- **Diagram colour key** (used in every figure): terracotta = model call · sage = deterministic code · ochre = human · dashed outline = data or external system.
- **Quoted output** in a chapter is preceded by `<!-- expected-output: code/... -->`; `verify.py` fails if the quote drifts from the real run.
- **Numbers** in cost and latency models are illustrative, and the text labels them that way.
