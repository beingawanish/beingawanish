# Part 3 — Multi-agent coordination

> In Part 3, **several model-driven agents with distinct roles** work on one job, and sometimes a human is one of them. The design question shifts from "what should the agent do?" to "who decides, who judges, and what does each one see?"

A second agent is worth adding for one of three reasons: it brings **different instructions** (a specialist), it brings **different tools or authority** (a reviewer that can run tests, a human who can approve a refund), or it brings an **independent view** (a peer who might disagree). If a proposed agent brings none of these, it is just another prompt, and a [chain](../part-1-workflow/01-prompt-chaining.md) or a [router](../part-1-workflow/02-routing.md) will do the job more cheaply.

The seven patterns differ in topology and in who holds authority:

| Pattern | Topology | Who decides what happens next | Who judges |
|---|---|---|---|
| [12. Supervisor](12-supervisor.md) | hub and spoke | one supervisor, every turn | the supervisor |
| [13. Hierarchical teams](13-hierarchical-teams.md) | tree | a lead at each level | each level's lead |
| [14. Sequential handoffs](14-sequential-handoffs.md) | chain chosen at runtime | the current owner | the current owner |
| [15. Debate](15-debate.md) | peers, then a judge | fixed rounds | a judge (or consensus) |
| [16. Critic–reviewer loop](16-critic-reviewer.md) | author ↔ reviewer | the review status | the reviewer, with tools |
| [17. Human-in-the-loop](17-human-in-the-loop.md) | agent → checkpoint → human | a code policy | a person |
| [18. Swarm](18-swarm.md) | many peers, shared board | nobody (local rules) | nobody (emergent) |

**Three costs come with every extra agent.** First, *coordination calls*: every hand-off, delegation or round is a model call that does no work itself. Second, *context duplication*: shared facts get re-sent to each agent that needs them. Third, *debuggability*: a failure now has a cast of suspects. The hierarchical-teams example measures the first two directly: more calls, smaller contexts. Each chapter's usage guidance tells you how to keep the third under control.

**Read the swarm chapter last, and honestly.** It is in the catalog because you will be asked about it and because the blackboard idea is genuinely useful. It is also the pattern whose "when not to use" section is longer than its "when to use" section.

The part ends with the [coding-team capstone](../capstones/coding-team.md): a supervisor over hierarchical teams, with a tool-using developer, a critic–reviewer QA loop, and context management keeping every prompt within budget.
