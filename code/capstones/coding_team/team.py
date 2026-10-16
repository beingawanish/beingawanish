"""Multi-agent coding team: the glue. Every pattern used here is imported, not re-implemented."""

from __future__ import annotations

from typing import Optional

from agentkit import LLM, Trace, extract_json
from capstones.coding_team.repo import TOOL_DOCS, make_tools, run_tests
from patterns.context_management.context import ContextManager, ContextReport, loop_render
from patterns.critic_reviewer.review import Finding, Response, review_loop
from patterns.hierarchical_teams.teams import team_as_worker
from patterns.supervisor.supervisor import Supervisor
from patterns.tool_use_loop.loop import ToolLoop

DEV_SYSTEM = "You are the developer. Change code only through tools. Keep existing behaviour unless asked."


class CodingTeam:
    def __init__(self, files: dict[str, str], dev_llm: LLM, summarizer: LLM, qa_llm: LLM,
                 leads: dict[str, LLM], budget: int = 300, trace: Optional[Trace] = None) -> None:
        self.files, self.dev_llm, self.summarizer, self.qa_llm = files, dev_llm, summarizer, qa_llm
        self.tools = make_tools(files)
        self.budget, self.trace = budget, trace
        self.context_log: list[ContextReport] = []
        self.compactions = 0

        dev_team = Supervisor(leads["dev"], {"developer": self.developer}, {"developer": "changes code via tools"},
                              name="dev_lead")
        qa_team = Supervisor(leads["qa"], {"reviewer": self.review}, {"reviewer": "reviews and gets fixes made"},
                             name="qa_lead")
        self.lead = Supervisor(leads["tech"], {"dev_team": team_as_worker(dev_team, trace=trace),
                                               "qa_team": team_as_worker(qa_team, trace=trace)},
                               {"dev_team": "implements changes", "qa_team": "independent review"}, name="tech_lead")

    # R3 + R5: the developer is a tool-use loop whose prompt is assembled by a context manager.
    def developer(self, instruction: str, state: dict) -> str:
        cm = ContextManager(self.budget, self.summarizer, keep_recent=4)
        loop = ToolLoop(self.dev_llm, self.tools, system=DEV_SYSTEM, max_steps=8,
                        render=loop_render(cm, instruction, TOOL_DOCS, log=self.context_log))
        result = loop.run(instruction, trace=self.trace)
        self.compactions += cm.summarizer_calls
        return result.final or f"[developer stopped: {result.stop_reason}]"

    # R4: QA's reviewer uses its own tools (the test runner and repository checks).
    def qa_findings(self, _artefact: str) -> list[Finding]:
        res = run_tests(self.files)
        evidence = [f"tests: passed={res['passed']} failed={res['failed']}"]
        if not any("--json" in src for p, src in self.files.items() if p.startswith("test_")):
            evidence.append("check: no test mentions --json")
        if "--json" not in self.files["cli.py"].split("\n", 1)[0]:
            evidence.append("check: USAGE line does not mention --json")
        raw = self.qa_llm.complete("REVIEW the change. Evidence:\n" + "\n".join(evidence) + "\nReturn findings JSON.")
        return [Finding(**f) for f in extract_json(raw)]

    def _snapshot(self) -> str:
        return "\n".join(f"--- {p}\n{src}" for p, src in sorted(self.files.items()))

    def _author(self, task: str, current: Optional[str], findings: list[Finding]):
        if not findings:
            return self._snapshot(), []
        listing = "\n".join(f"{f.id} [{f.severity}] {f.issue}" for f in findings)
        note = self.developer(f"Address review findings for: {task}\n{listing}", {})
        return self._snapshot(), [Response(f.id, "fixed", note) for f in findings]

    def review(self, instruction: str, state: dict) -> str:
        run = review_loop(instruction, self._author, self.qa_findings, max_rounds=3, trace=self.trace)
        blocking = [f.id for f in run.open_findings if f.severity == "blocking"]
        self.review_run = run
        return f"approved={run.approved} after {run.rounds} review round(s); open blocking findings={blocking or 'none'}"

    def run(self, request: str):
        return self.lead.run(request, trace=self.trace)
