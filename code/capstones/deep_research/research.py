"""Deep-research agent: the glue. Every pattern used here is imported, not re-implemented."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from agentkit import LLM, Trace
from patterns.agentic_rag.rag import Retriever, agentic_rag
from patterns.evaluator_optimizer.optimizer import OptimizeResult, optimize
from patterns.memory_tiers.memory import SemanticMemory, Store
from patterns.plan_and_execute.planner import StepResult, plan_and_execute
from patterns.reflection.reflect import reflect

ACTIONS = {"research": "answer one sub-question from the sources (args: question, topic)"}
RUBRIC = [
    "Every sentence that states a number or a capability cites a source like [src-id]",
    "Covers every topic the question asks about",
    "States what is uncertain or vendor-reported",
    "Under 160 words",
]
CITE = re.compile(r"\[(src-[\w-]+)\]")


@dataclass
class ResearchReport:
    question: str
    findings: dict[str, str] = field(default_factory=dict)
    report: str = ""
    plan_versions: int = 0
    rag_calls: int = 0
    memory_hits: list[str] = field(default_factory=list)
    eval: Optional[OptimizeResult] = None


class CountingLLM:
    """Counts calls made by one component (here: the retrieval agent)."""

    def __init__(self, inner: LLM) -> None:
        self.inner, self.calls = inner, 0

    def complete(self, prompt: str, system: str = "") -> str:
        self.calls += 1
        return self.inner.complete(prompt, system)


class DeepResearcher:
    def __init__(self, planner: LLM, rag_llm: LLM, writer: LLM, evaluator: LLM,
                 corpus: dict[str, str], memory_path, session: str) -> None:
        self.planner, self.writer, self.evaluator = planner, writer, evaluator
        self.rag_llm = CountingLLM(rag_llm)
        self.retriever = Retriever(corpus)
        self.memory = SemanticMemory(Store(memory_path))
        self.session = session

    # R1 + R2 + R3: one plan step = recall from memory, else research with agentic RAG.
    def _execute(self, report: ResearchReport, trace: Optional[Trace]):
        def run(step, results) -> StepResult:
            topic, q = step.args["topic"], step.args["question"]
            known = self.memory.get(f"finding:{topic}")
            if known:
                report.memory_hits.append(topic)
                report.findings[topic] = known.value
                return StepResult(True, known.value, "from memory")
            r = agentic_rag(self.rag_llm, self.retriever, q, max_queries=2, skip_route=True, trace=trace)
            if r.stop_reason != "answered":
                return StepResult(False, None, f"no sources for '{q}'")
            report.findings[topic] = r.answer
            self.memory.upsert(f"finding:{topic}", r.answer, [topic, "research"], source=q, session=self.session)
            return StepResult(True, r.answer)
        return run

    def research(self, question: str, trace: Optional[Trace] = None) -> ResearchReport:
        report = ResearchReport(question)
        run = plan_and_execute(self.planner, question, ACTIONS, self._execute(report, trace),
                               max_replans=2, trace=trace)
        report.plan_versions = len(run.plans)
        report.rag_calls = self.rag_llm.calls
        if not run.ok:
            report.report = f"Research incomplete: {run.stop_reason}"
            return report

        findings = "\n".join(f"- {t}: {f}" for t, f in report.findings.items())
        task = f"Recommendation for: {question}\nFindings (cite exactly as given):\n{findings}"
        # R4: the writer critiques its own draft first (cheap, same model) ...
        draft = reflect(self.writer, task, max_rounds=1, trace=trace).output
        # R5: ... then a separate evaluator holds it to the rubric.
        writer, first = self.writer, {"used": False}

        class StartFromDraft:  # optimize() starts with "WRITE:"; hand it the reflected draft instead
            def complete(self, prompt, system=""):
                if prompt.startswith("WRITE:") and "REVISE" not in prompt and not first["used"]:
                    first["used"] = True
                    return draft
                return writer.complete(prompt, system)

        report.eval = optimize(StartFromDraft(), self.evaluator, task, RUBRIC, max_rounds=3, trace=trace)
        report.report = report.eval.output
        return report


def citation_problems(report: str, corpus: dict[str, str]) -> list[str]:
    """Acceptance check in code: numbers need citations; citations must exist."""
    problems = [f"unknown source {c}" for c in CITE.findall(report) if c not in corpus]
    for sentence in re.split(r"(?<=[.!?])\s+", report):
        if re.search(r"\d", re.sub(r"\[src-[\w-]+\]", "", sentence)) and not CITE.search(sentence):
            problems.append(f"uncited number: {sentence[:50]}…")
    return problems
