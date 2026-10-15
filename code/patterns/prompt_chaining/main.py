"""Prompt chaining demo: release notes -> facts -> announcement -> social post.

Run:  python3 code/patterns/prompt_chaining/main.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.prompt_chaining.chain import Step, run_chain  # noqa: E402

# --- The steps (this is the whole "architecture") ----------------------------------

def facts_gate(out: str):
    if out.startswith("NO_USER_FACING_CHANGES"):
        return "nothing user-facing to announce"
    if not re.match(r"v\d+\.\d+", out):
        return "first line must be the version number"
    if out.count("- ") < 2:
        return "need at least two user-facing changes"
    return None


def length_gate(out: str):
    return None if len(out) <= 200 else f"post is {len(out)} chars (max 200)"


STEPS = [
    Step("extract",
         "Extract the USER-FACING changes from these release notes. First line: the version. "
         "Then one '- ' bullet per change. If none, reply NO_USER_FACING_CHANGES.\n\n{input}",
         gate=facts_gate),
    Step("draft", "Write a friendly customer announcement from these facts:\n\n{input}"),
    Step("compress", "Rewrite as one social post of at most 200 characters:\n\n{input}",
         gate=length_gate),
]

# --- The mock model's behaviour, in one place ---------------------------------------

mock = MockLLM(rules([
    (lambda p, s: "USER-FACING" in p and "dark mode" in p,
     "v2.4\n- Dark mode across all screens\n- CSV export for reports\n- 40% faster search"),
    (lambda p, s: "USER-FACING" in p,
     "NO_USER_FACING_CHANGES"),
    ("customer announcement",
     "Big news: version 2.4 is here! You asked, we listened: dark mode now covers every screen, "
     "you can export any report to CSV, and search is 40% faster. Update today and enjoy."),
    ("social post",
     "v2.4 is live: dark mode everywhere, CSV export for reports, and 40% faster search. Update now!"),
]))

GOOD_NOTES = """Release 2.4
* feat(ui): dark mode across all screens
* feat(reports): CSV export
* perf(search): new index, ~40% faster
* chore: bump lint rules"""

INTERNAL_NOTES = """Release 2.4.1
* chore: migrate CI to new runners
* refactor: split billing module"""


def main() -> None:
    trace = Trace("Prompt chaining")
    trace.note("-- run 1: release with user-facing changes")
    r1 = run_chain(mock, STEPS, GOOD_NOTES, trace)
    trace.note(f"result: ok={r1.ok} ({len(r1.output)} chars)")
    calls_after_run1 = mock.usage.calls

    trace.note("-- run 2: internal-only release")
    r2 = run_chain(mock, STEPS, INTERNAL_NOTES, trace)
    trace.note(f"result: ok={r2.ok} stopped_at={r2.stopped_at}")
    trace.note(f"calls: run1={calls_after_run1}, run2={mock.usage.calls - calls_after_run1}")
    trace.print()

    assert r1.ok and len(r1.output) <= 200
    assert not r2.ok and r2.stopped_at == "extract"
    assert mock.usage.calls == 4  # the gate saved two calls on run 2


if __name__ == "__main__":
    main()
