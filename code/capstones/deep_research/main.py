"""Deep-research capstone: a researched, cited recommendation; then a follow-up
question in a new session that is answered from memory.

Run:  python3 code/capstones/deep_research/main.py
"""

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from capstones.deep_research.fixtures import (  # noqa: E402
    CORPUS, FOLLOW_UP, QUESTION, TOPICS, make_evaluator, make_planner, make_rag_llm, make_writer,
)
from capstones.deep_research.research import DeepResearcher, citation_problems  # noqa: E402


def build(path, session):
    return DeepResearcher(make_planner(), make_rag_llm(), make_writer(), make_evaluator(), CORPUS, path, session)


def main() -> None:
    trace = Trace("Deep-research capstone", width=110)
    with tempfile.TemporaryDirectory() as tmp:
        mem = pathlib.Path(tmp) / "memory.json"

        trace.note("-- session 1: " + QUESTION)
        r1 = build(mem, "s1").research(QUESTION, trace=trace)
        trace.note("-- final report")
        trace.note(r1.report)

        trace.note("-- session 2 (new process): " + FOLLOW_UP)
        r2 = build(mem, "s2").research(FOLLOW_UP, trace=trace)

    covered = [t for t, src in TOPICS.items() if f"[{src}]" in r1.report]
    problems = citation_problems(r1.report, CORPUS) + citation_problems(r2.report, CORPUS)
    checks = {
        "coverage": (f"{len(covered)}/4 topics cited", len(covered) == 4),
        "citation integrity": (f"{len(problems)} problems", not problems),
        "unsupported claims": ("'near-zero' removed" if "near-zero" not in r1.report else "overclaim survived",
                               "near-zero" not in r1.report),
        "evaluator": (f"passed={r1.eval.passed} in {r1.eval.rounds} round(s)", r1.eval.passed and r1.eval.rounds <= 3),
        "follow-up from memory": (f"retrieval-agent calls={r2.rag_calls}, memory hits={r2.memory_hits}",
                                  r2.rag_calls == 0 and set(r2.memory_hits) == {"cost", "downtime"}),
    }
    trace.note("-- acceptance")
    trace.note(f"session 1: plan versions={r1.plan_versions}, retrieval-agent calls={r1.rag_calls}")
    for name, (detail, ok) in checks.items():
        trace.step("PASS" if ok else "FAIL", f"{name}: {detail}")
    trace.print()
    assert all(ok for _, ok in checks.values()), "acceptance criteria failed"


if __name__ == "__main__":
    main()
