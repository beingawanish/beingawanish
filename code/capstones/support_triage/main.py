"""Support triage capstone: one ticket traced end to end, then the full eval against the brief.

Run:  python3 code/capstones/support_triage/main.py
"""

import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from capstones.support_triage.fixtures import CASES, TICKETS, make_judge, make_llm, make_tools  # noqa: E402
from capstones.support_triage.triage import TriageSystem  # noqa: E402
from patterns.eval_harness.harness import field_equals, format_report, llm_judge, run_eval  # noqa: E402
from patterns.guardrailed_generation.guardrails import CARD_NUMBER  # noqa: E402
from patterns.human_in_the_loop.hitl import ReviewQueue  # noqa: E402

THRESHOLDS = {"route_correct": 0.85, "status_correct": 1.0, "pii_safe": 1.0, "quality": 0.80}


def pii_safe(case, out) -> float:
    return 0.0 if re.search(CARD_NUMBER, out["reply"]) else 1.0


def build(tmp: pathlib.Path):
    llm, outbox = make_llm(), []
    system = TriageSystem(llm, make_tools(), ReviewQueue(tmp / "queue.json"), outbox)
    return system, llm, outbox


def main() -> None:
    trace = Trace("Support triage capstone")
    with tempfile.TemporaryDirectory() as tmp:
        # 1. Walkthrough: the hardest ticket, traced.
        system, _, _ = build(pathlib.Path(tmp))
        trace.note("-- walkthrough: TK-108 (card number in the ticket)")
        system.handle(TICKETS[7], trace=trace)

    with tempfile.TemporaryDirectory() as tmp:
        # 2. Full eval on a fresh system.
        system, llm, outbox = build(pathlib.Path(tmp))

        def run(ticket):
            o = system.handle(ticket)
            return {"route": o.route, "status": o.status, "reply": o.reply, "refund": o.refund}

        scorers = [field_equals("route"), field_equals("status"), pii_safe,
                   llm_judge(make_judge(), "Is the reply correct, specific and polite?", name="quality")]
        report = run_eval("support-triage v1", run, CASES, scorers)

        trace.note("-- eval")
        for r in report.results:
            trace.step(r.case.id, f"{r.output['route']:<9} {r.output['status']:<7} refund={r.output['refund']}")
        trace.note(format_report(report, tags=("critical",)))
        sent = sum(r.output["status"] == "sent" for r in report.results)
        trace.note(f"auto-send rate: {sent}/{len(report.results)}; outbox={len(outbox)}; "
                   f"pending review: {', '.join(system.queue.pending())}")
        trace.note(f"model usage: {llm.usage.summary()}")
        trace.note("-- acceptance")
        failed = []
        for metric, threshold in THRESHOLDS.items():
            value = report.mean(metric)
            ok = value >= threshold
            failed += [] if ok else [metric]
            trace.step("PASS" if ok else "FAIL", f"{metric} {value:.2f} (>= {threshold:.2f})")
    trace.print()
    assert not failed, f"acceptance criteria failed: {failed}"


if __name__ == "__main__":
    main()
