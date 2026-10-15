"""Exercise solution — Context management.

Task: summaries are lossy. A cheaper summarizer drops the incident id INC-4411, so
the agent can no longer reference the incident it is working on. Make
identifiers survive compaction *verbatim*: extract ticket-style ids from turns
before they are summarised and keep them in a pinned line of the summary.

Run:  python3 code/patterns/context_management/exercise_solution.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.context_management.context import ContextManager  # noqa: E402
from patterns.context_management.main import DOCS, SYSTEM, TASK, TOOLS, TRANSCRIPT  # noqa: E402

ID = re.compile(r"\b[A-Z]{2,6}-\d+\b")
lossy = MockLLM(lambda p, s: "Payments-api errors began after a deploy; a rollback was approved.")


class PinningContextManager(ContextManager):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.pinned: list[str] = []

    def _compact(self, transcript):
        for turn in transcript[self.summarized_upto: max(0, len(transcript) - self.keep_recent)]:
            self.pinned += [i for i in ID.findall(turn) if i not in self.pinned]
        recent = super()._compact(transcript)
        if self.pinned and "PINNED IDS" not in self.summary:
            self.summary += f" PINNED IDS: {', '.join(self.pinned)}."
        return recent


def main() -> None:
    trace = Trace("Context management — exercise solution")
    for label, cls in (("plain", ContextManager), ("pinning", PinningContextManager)):
        cm = cls(budget=300, summarizer=lossy, keep_recent=3)
        prompt, rep = cm.assemble(SYSTEM, TASK, TOOLS, set(), TRANSCRIPT, DOCS)
        trace.step(label, f"CHG-881 in context={'CHG-881' in prompt}, INC-4411 in context={'INC-4411' in prompt}, "
                          f"tokens={rep.total}")
    trace.print()
    assert "CHG-881" in prompt and "INC-4411" in prompt


if __name__ == "__main__":
    main()
