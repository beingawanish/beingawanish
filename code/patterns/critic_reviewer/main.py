"""Critic–reviewer demo: an author agent writes `slugify`; a reviewer agent that can run
tests and a linter files findings; blocking findings get fixed, a nit is declined
with a reason, and the reviewer approves in round 2.

Run:  python3 code/patterns/critic_reviewer/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, extract_json  # noqa: E402
from patterns.critic_reviewer.review import Finding, Response, review_loop  # noqa: E402

V1 = 'def slugify(s):\n    return s.lower().replace(" ", "-")'
V2 = ('import re, unicodedata\n\ndef slugify(s):\n'
      '    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()\n'
      '    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")')

TESTS = [("Hello World", "hello-world"), ("  Spaces  ", "spaces"), ("Crème brûlée", "creme-brulee"), ("a--b", "a-b")]


# --- The reviewer's tools: real checks on the real code string -------------------------
def run_tests(code: str) -> list[str]:
    ns: dict = {}
    exec(code, ns)  # our own deterministic artefacts; sandbox real model output in production
    return [f"slugify({i!r}) == {ns['slugify'](i)!r}, expected {o!r}" for i, o in TESTS if ns["slugify"](i) != o]


def lint(code: str) -> list[str]:
    return [] if '"""' in code else ["slugify has no docstring"]


# --- The reviewer agent: tool output in, judged findings out ---------------------------
reviewer_llm = MockLLM(lambda p, s: json.dumps(
    # keyed on the *actual* outputs in the tool evidence, so each finding states what is really wrong
    ([{"id": "F1", "severity": "blocking", "issue": "accents are not transliterated"}] if "crème" in p else []) +
    ([{"id": "F2", "severity": "blocking", "issue": "separators wrong: want single dashes between words, none at ends"}]
     if "'  Spaces  '" in p or "'a--b'" in p else []) +
    ([{"id": "F3", "severity": "nit", "issue": "add a docstring"}] if "no docstring" in p else [])),
    name="reviewer")


def reviewer(code: str) -> list[Finding]:
    evidence = "\n".join(run_tests(code) + lint(code)) or "all checks pass"
    raw = reviewer_llm.complete(f"REVIEW. Tool results:\n{evidence}\nReturn findings as JSON list.")
    return [Finding(**f) for f in extract_json(raw)]


# --- The author agent --------------------------------------------------------------------
author_llm = MockLLM(lambda p, s: json.dumps({
    "code": V2,
    "responses": [{"finding_id": "F1", "action": "fixed", "note": "NFKD + ASCII fold"},
                  {"finding_id": "F2", "action": "fixed", "note": "collapse non-alnum runs, strip dashes"},
                  {"finding_id": "F3", "action": "wont_fix", "note": "one-line helper; the name is the doc"}],
}) if "FINDINGS" in p else json.dumps({"code": V1, "responses": []}), name="author")


def author(task, current, findings):
    listing = "\n".join(f"{f.id} [{f.severity}] {f.issue}" for f in findings)
    raw = author_llm.complete(f"TASK: {task}\nCURRENT:\n{current}\nFINDINGS:\n{listing}" if findings else f"TASK: {task}")
    msg = extract_json(raw)
    return msg["code"], [Response(**r) for r in msg["responses"]]


def main() -> None:
    trace = Trace("Critic–reviewer loop")
    run = review_loop("Write slugify(s) for URL slugs", author, reviewer, trace=trace)
    trace.note(f"result: approved={run.approved} in {run.rounds} rounds; remaining findings: "
               f"{[f.id for f in run.open_findings] or 'none'}; tests failing now: {len(run_tests(run.artefact))}")
    trace.note(f"calls: author={author_llm.usage.calls}, reviewer={reviewer_llm.usage.calls}")
    trace.print()

    assert run.approved and run.rounds == 2 and run_tests(run.artefact) == []


if __name__ == "__main__":
    main()
