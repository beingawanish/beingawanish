"""Eval harness: fixed cases + scorers -> report; compare two reports -> ship/block.

Canonical module: the support-triage capstone imports this file.

Principles encoded here:
* Cases are data (id, input, expected, tags), versioned with the code.
* Scorers are small functions returning 0.0..1.0. Deterministic scorers come first;
  LLM-judge scorers are allowed but must return parseable scores or score 0.
* A system crash on a case is a score of 0, recorded — never an aborted run.
* Comparison is per case, not just per average: an improved mean can hide a regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Callable, Optional

from agentkit import LLM, extract_json


@dataclass
class Case:
    id: str
    input: Any
    expected: dict[str, Any]
    tags: tuple[str, ...] = ()


Scorer = Callable[[Case, Any], float]


# --- Scorers -------------------------------------------------------------------------

def field_equals(key: str) -> Scorer:
    def score(case: Case, out: Any) -> float:
        return 1.0 if isinstance(out, dict) and out.get(key) == case.expected.get(key) else 0.0
    score.__name__ = f"{key}_correct"
    return score


def at_most(key: str, limit: float) -> Scorer:
    def score(case: Case, out: Any) -> float:
        return 1.0 if isinstance(out, dict) and out.get(key, float("inf")) <= limit else 0.0
    score.__name__ = f"{key}<={limit:g}"
    return score


def llm_judge(judge: LLM, rubric: str, name: str = "judge", pass_mark: float = 0.7) -> Scorer:
    """Ask a judge model for {"score": 0..1}. Unparseable verdicts score 0 (fail closed).

    Use a *different* model (or at least a different prompt and temperature) from the
    system under test: a model grading its own output inflates scores.
    """

    def score(case: Case, out: Any) -> float:
        prompt = f"JUDGE.\nRubric: {rubric}\nInput: {case.input}\nOutput: {out}\nReply {{\"score\": 0..1}}"
        try:
            return max(0.0, min(1.0, float(extract_json(judge.complete(prompt))["score"])))
        except (ValueError, KeyError, TypeError):
            return 0.0
    score.__name__ = name
    score.pass_mark = pass_mark  # graded scorer: a case "fails" below this mark
    return score


# --- Running -------------------------------------------------------------------------

@dataclass
class CaseResult:
    case: Case
    output: Any
    scores: dict[str, float]
    error: Optional[str] = None


@dataclass
class Report:
    name: str
    results: list[CaseResult] = field(default_factory=list)
    pass_marks: dict[str, float] = field(default_factory=dict)  # binary scorers default to 1.0

    def scorer_names(self) -> list[str]:
        return list(self.results[0].scores) if self.results else []

    def mean(self, scorer: str, tag: Optional[str] = None) -> float:
        rows = [r for r in self.results if tag is None or tag in r.case.tags]
        return mean(r.scores[scorer] for r in rows) if rows else 0.0

    def failures(self, scorer: str) -> list[str]:
        mark = self.pass_marks.get(scorer, 1.0)
        return [r.case.id for r in self.results if r.scores[scorer] < mark]


def run_eval(name: str, system: Callable[[Any], Any], cases: list[Case], scorers: list[Scorer]) -> Report:
    report = Report(name, pass_marks={s.__name__: getattr(s, "pass_mark", 1.0) for s in scorers})
    for case in cases:
        try:
            out, err = system(case.input), None
            scores = {s.__name__: s(case, out) for s in scorers}
        except Exception as exc:  # a crash is a zero, not an aborted eval
            out, err = None, f"{type(exc).__name__}: {exc}"
            scores = {s.__name__: 0.0 for s in scorers}
        report.results.append(CaseResult(case, out, scores, err))
    return report


@dataclass
class Comparison:
    deltas: dict[str, tuple[float, float]]           # scorer -> (baseline, candidate)
    regressions: list[tuple[str, str, bool]]          # (case_id, scorer, is_critical)
    fixes: list[tuple[str, str]]                      # (case_id, scorer)

    @property
    def verdict(self) -> str:
        critical = [r for r in self.regressions if r[2]]
        if critical:
            return f"BLOCK — {len(critical)} critical regression(s)"
        worse = [s for s, (b, c) in self.deltas.items() if c < b]
        if worse:
            return f"BLOCK — mean dropped on {', '.join(worse)}"
        return "SHIP" + (f" (with {len(self.regressions)} non-critical regression(s))" if self.regressions else "")


def compare(baseline: Report, candidate: Report, critical_tag: str = "critical") -> Comparison:
    base = {r.case.id: r for r in baseline.results}
    deltas = {s: (baseline.mean(s), candidate.mean(s)) for s in baseline.scorer_names()}
    regressions, fixes = [], []
    for r in candidate.results:
        b = base.get(r.case.id)
        if b is None:
            continue
        for s, score in r.scores.items():
            if score < b.scores[s]:
                regressions.append((r.case.id, s, critical_tag in r.case.tags))
            elif score > b.scores[s]:
                fixes.append((r.case.id, s))
    return Comparison(deltas, regressions, fixes)


def format_report(report: Report, tags: tuple[str, ...] = ()) -> str:
    lines = [f"{report.name}:"]
    for s in report.scorer_names():
        by_tag = "".join(f"  [{t}] {report.mean(s, t):.2f}" for t in tags)
        fails = report.failures(s)
        lines.append(f"  {s:<16} {report.mean(s):.2f}{by_tag}  fails: {', '.join(fails) or '-'}")
    errors = [r.case.id for r in report.results if r.error]
    if errors:
        lines.append(f"  crashed on: {', '.join(errors)}")
    return "\n".join(lines)


def format_comparison(c: Comparison) -> str:
    lines = ["comparison:"]
    for s, (b, cand) in c.deltas.items():
        lines.append(f"  {s:<16} {b:.2f} -> {cand:.2f} ({cand - b:+.2f})")
    lines.append("  fixed:      " + (", ".join(f"{i}/{s}" for i, s in c.fixes) or "-"))
    lines.append("  regressed:  " + (", ".join(f"{i}/{s}{' (critical)' if k else ''}"
                                             for i, s, k in c.regressions) or "-"))
    lines.append(f"  verdict:    {c.verdict}")
    return "\n".join(lines)
