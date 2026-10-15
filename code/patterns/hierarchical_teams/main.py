"""Hierarchical teams demo: a launch lead runs a research team and a content team;
compared with one flat supervisor over the same four workers.

Run:  python3 code/patterns/hierarchical_teams/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.hierarchical_teams.teams import team_as_worker  # noqa: E402
from patterns.supervisor.supervisor import Supervisor  # noqa: E402

NOTES = " ".join(["Interview note: customers export weekly reports by hand and want it automated."] * 6)


def market_researcher(i, s):
    return "Findings: 62% of surveyed admins export reports weekly. " + NOTES


def data_analyst(i, s):
    return "Usage data: 41% of active teams used CSV export last month; median 3 exports/week. " + NOTES


def writer(i, s):
    return "Draft: Scheduled exports are here — set it once, get your report every Monday."


def editor(i, s):
    return "Edited: Scheduled exports: set it once and your report arrives every Monday."


def lead(order, final):
    """A deterministic supervisor policy: call workers in order, then FINISH with `final`."""
    def decide(prompt, system):
        history = prompt.split("History:\n", 1)[1]
        for name, instruction in order:
            if f"[{name}]" not in history:
                return json.dumps({"next": name, "instruction": instruction})
        return json.dumps({"next": "FINISH", "final": final})
    return decide


RESEARCH_SUMMARY = "Demand is real: 62% export weekly by hand; 41% of teams used CSV export last month."
CONTENT_SUMMARY = "Headline: 'Scheduled exports: set it once and your report arrives every Monday.'"


def main() -> None:
    trace = Trace("Hierarchical teams", width=100)
    calls = {}

    research_llm = MockLLM(lead([("market_researcher", "Survey admins about exports"),
                                 ("data_analyst", "Pull CSV export usage")], RESEARCH_SUMMARY))
    content_llm = MockLLM(lead([("writer", "Draft the launch headline"),
                                ("editor", "Tighten the headline")], CONTENT_SUMMARY))
    top_llm = MockLLM(lead([("research_team", "Establish demand for scheduled exports"),
                            ("content_team", "Write the launch headline")], CONTENT_SUMMARY))
    research = Supervisor(research_llm, {"market_researcher": market_researcher, "data_analyst": data_analyst},
                          {"market_researcher": "surveys", "data_analyst": "usage data"}, name="research_lead")
    content = Supervisor(content_llm, {"writer": writer, "editor": editor},
                         {"writer": "drafts", "editor": "edits"}, name="content_lead")
    top = Supervisor(top_llm, {"research_team": team_as_worker(research, trace=trace),
                               "content_team": team_as_worker(content, trace=trace)},
                     {"research_team": "evidence of demand", "content_team": "launch copy"}, name="launch_lead")

    trace.note("-- hierarchical: launch_lead → {research_lead, content_lead} → 4 workers")
    r = top.run("Prepare the scheduled-exports launch", trace=trace)
    for name, llm in (("launch_lead", top_llm), ("research_lead", research_llm), ("content_lead", content_llm)):
        calls[name] = (llm.usage.calls, max(len(c.prompt.split()) for c in llm.calls))

    trace.note("-- flat: one supervisor over the same 4 workers")
    flat_llm = MockLLM(lead([("market_researcher", "Survey admins"), ("data_analyst", "Pull usage"),
                             ("writer", "Draft headline"), ("editor", "Tighten headline")], CONTENT_SUMMARY))
    flat = Supervisor(flat_llm, {"market_researcher": market_researcher, "data_analyst": data_analyst,
                                 "writer": writer, "editor": editor},
                      {"market_researcher": "surveys", "data_analyst": "usage", "writer": "drafts", "editor": "edits"},
                      name="flat_lead")
    f = flat.run("Prepare the scheduled-exports launch")
    flat_max = max(len(c.prompt.split()) for c in flat_llm.calls)

    trace.note("-- comparison (supervisor calls; largest supervisor prompt in words)")
    for name, (n, biggest) in calls.items():
        trace.step(name, f"{n} calls, largest prompt {biggest} words")
    trace.step("flat_lead", f"{flat_llm.usage.calls} calls, largest prompt {flat_max} words")
    trace.print()

    assert r.ok and f.ok and r.final == f.final
    assert calls["launch_lead"][1] < flat_max / 2          # the top lead never sees team-internal detail
    assert sum(n for n, _ in calls.values()) > flat_llm.usage.calls  # ...at the price of more coordination calls


if __name__ == "__main__":
    main()
