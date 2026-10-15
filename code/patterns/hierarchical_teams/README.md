# Pattern 13 — Hierarchical teams

Supervisors of supervisors, with scoped context per team and summaries flowing up.

| | |
|---|---|
| Implementation | [`teams.py`](teams.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-3-multi-agent/13-hierarchical-teams.md`](../../../book/part-3-multi-agent/13-hierarchical-teams.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/hierarchical_teams/main.py
```

## Expected output

```text
Hierarchical teams
==================
-- hierarchical: launch_lead → {research_lead, content_lead} → 4 workers
[launch_lead → research_team] Establish demand for scheduled exports
[research_lead → market_researcher] Survey admins about exports
[market_researcher] Findings: 62% of surveyed admins export reports weekly. Interview note: customers export weekly rep…
[research_lead → data_analyst] Pull CSV export usage
[data_analyst] Usage data: 41% of active teams used CSV export last month; median 3 exports/week. Interview note:…
[research_lead] FINISH: Demand is real: 62% export weekly by hand; 41% of teams used CSV export last month.
[research_team] Demand is real: 62% export weekly by hand; 41% of teams used CSV export last month.
[launch_lead → content_team] Write the launch headline
[content_lead → writer] Draft the launch headline
[writer] Draft: Scheduled exports are here — set it once, get your report every Monday.
[content_lead → editor] Tighten the headline
[editor] Edited: Scheduled exports: set it once and your report arrives every Monday.
[content_lead] FINISH: Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
[content_team] Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
[launch_lead] FINISH: Headline: 'Scheduled exports: set it once and your report arrives every Monday.'
-- flat: one supervisor over the same 4 workers
-- comparison (supervisor calls; largest supervisor prompt in words)
[launch_lead] 3 calls, largest prompt 67 words
[research_lead] 3 calls, largest prompt 203 words
[content_lead] 3 calls, largest prompt 60 words
[flat_lead] 5 calls, largest prompt 237 words
```

> **Reused, not copied:** the coding-team capstone imports this module.

Verified by `python3 code/verify.py hierarchical_teams`.
