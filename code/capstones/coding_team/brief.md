# Capstone brief — Multi-agent coding team

*Spec first. This brief was written before the solution; the solution is judged against it.*

## Problem

A small repository contains a reporting CLI (`cli.py`) and its tests. The request:
*"Add a `--json` flag that prints the report as JSON. Text output must not change."*
Build a team of agents that implements the change, gets it independently reviewed,
addresses the review, and finishes with every test passing, without any single
agent's context growing without bound.

## Inputs and outputs

- **Input:** a virtual repository `{path: source}` and the request.
- **Output:** the changed repository, the review record, and per-agent context statistics.

## Requirements

| ID | Requirement | Pattern |
|----|-------------|---------|
| R1 | A tech lead coordinates the work turn by turn and decides when it is done. | Supervisor (#12) |
| R2 | The lead delegates to a dev team and a QA team, each run by its own lead. The tech lead sees team summaries, never file contents. | Hierarchical teams (#13) |
| R3 | The developer works through tools (`read_file`, `write_file`, `run_tests`) with validated arguments and host-enforced limits. | Tool-use loop (#9) |
| R4 | QA reviews with its *own* tools (tests and checks), files itemised findings, and requires blocking findings to be fixed before approval. | Critic–reviewer loop (#16) |
| R5 | Every developer prompt fits a token budget: old turns compacted, tool docs disclosed on demand. | Context management (#20) |

## Acceptance criteria (checked by `main.py`, enforced by `verify.py`)

| Metric | Threshold |
|--------|-----------|
| All tests pass on the final repository (existing + new) | 100% |
| Existing text output unchanged | original tests pass unmodified |
| QA approval with zero open blocking findings | yes |
| Developer prompts within budget | every prompt ≤ 300 tokens; ≥ 1 compaction |
| Tech-lead context scoping | no file contents in any tech-lead prompt |

## Non-goals

Real git, real sandboxes, real CI, merge conflicts.

## Composition (no duplicate implementations)

Imports `patterns.supervisor.supervisor`, `patterns.hierarchical_teams.teams`,
`patterns.tool_use_loop.loop`, `patterns.critic_reviewer.review` and
`patterns.context_management.context`. The capstone owns `repo.py` (virtual repo and
tools), `team.py` (glue), `fixtures.py` (mock models) and `main.py`.

## Run

```
python3 code/capstones/coding_team/main.py
```
