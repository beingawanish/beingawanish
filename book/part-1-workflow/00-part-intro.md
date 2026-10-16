# Part 1 — Workflow patterns

> In a workflow, **your code owns the control flow**. The model fills in the steps; it never decides which step comes next.

That single property makes workflows the default starting point. A workflow can be read like a flowchart, tested like a function, and given a cost ceiling before it runs. In every Part 1 pattern you can predict the number of model calls, or at least bound it.

The five patterns differ in the shape of that control flow:

| Pattern | Shape | Who splits or judges the work |
|---|---|---|
| [1. Prompt chaining](01-prompt-chaining.md) | a line | code, at design time |
| [2. Routing](02-routing.md) | a fork with exactly one branch taken | a classifier, once |
| [3. Parallelization](03-parallelization.md) | fan-out, fan-in | code, statically |
| [4. Orchestrator–workers](04-orchestrator-workers.md) | fan-out decided at runtime | a model, once |
| [5. Evaluator–optimizer](05-evaluator-optimizer.md) | a loop | a separate evaluator model |

Two ideas run through all five.

**Gates are code.** Between model calls, deterministic checks (a regex, a schema, a length limit, a known-route test) turn silent failures into explicit ones. They are almost free and they are the cheapest reliability you can buy. In this book they are always drawn in sage.

**Cost is countable.** Each chapter's usage guidance gives a formula in calls, tokens and wall-clock time. If you cannot write the formula for a design, it is probably not a workflow any more; check Parts 2 and 3.

**The ladder of escalation.** Use one well-prompted call if it is good enough. Use a chain when the task splits into distinct steps, a router when inputs differ in kind, parallelization when sub-checks are independent, orchestrator–workers when the split can only be known at runtime, and an evaluator loop when quality is measurable but rarely right the first time. Reach for agents (Part 2) only when the *sequence of steps* itself cannot be known in advance.

The Part 1 pilot ends with the [support-triage capstone](../capstones/support-triage.md). It composes routing and parallelization with three modules from later parts: guardrailed generation (#11), human-in-the-loop (#17) and the eval harness (#21).
