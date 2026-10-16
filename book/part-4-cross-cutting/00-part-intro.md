# Part 4 — Cross-cutting concerns

> Parts 1–3 are *structures*: who calls whom, in what shape. Part 4 is about *concerns* that every structure has: what the system remembers, what each call can see, and how you know any of it works.

These three patterns are not alternatives to the others; they apply *to* them. Every capstone in this book uses at least one:

| Pattern | The question it answers | Used by |
|---|---|---|
| [19. Memory tiers](19-memory-tiers.md) | What should survive beyond this call, this session, this process? | Deep-research capstone (findings reused across sessions) |
| [20. Context management](20-context-management.md) | What goes into *this* call's window, given a budget? | Coding-team capstone (developer prompts ≤ 300 tokens) |
| [21. Eval harness](21-eval-harness.md) | Is the new version better, and did anything get worse? | Support-triage capstone (acceptance thresholds) |

Two of them are easy to confuse, so here is the boundary again:

- **Memory** is about *time*: what is stored, how it is updated, how it is recalled later.
- **Context** is about *space*: what fits in one call, and what must be pinned, summarised or left out.

Compaction is where they touch. A summary written to keep this call small may also be worth storing in memory. The decision to *store* belongs to the memory write policy; the decision to *include* belongs to the context budget.

The **eval harness** is different in kind. It runs at development time, not at runtime. It is the reason the other twenty patterns can be changed safely: every claim in this book that "the new version is better" should be backed by a harness run, and every capstone ends with one.
