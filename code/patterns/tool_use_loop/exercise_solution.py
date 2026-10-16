"""Exercise solution — Tool-use loop.

Task: a model that loses track of its own progress may call `create_event` twice
with identical arguments, creating a duplicate meeting. Make side-effecting tools
idempotent *in the host*: an identical repeat call returns the earlier result with
a note, and never re-executes. Do not change ToolLoop.

Run:  python3 code/patterns/tool_use_loop/exercise_solution.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, ToolRegistry, Trace  # noqa: E402
from patterns.tool_use_loop.loop import ToolLoop  # noqa: E402


class IdempotentTools(ToolRegistry):
    """Same interface as ToolRegistry; dedupes calls to the named side-effecting tools."""

    def __init__(self, inner: ToolRegistry, side_effecting: set[str]):
        super().__init__()
        self.inner, self.side_effecting = inner, side_effecting
        self._done: dict[str, object] = {}

    def specs(self):
        return self.inner.specs()

    def call(self, name, args):
        if name not in self.side_effecting:
            return self.inner.call(name, args)
        key = name + json.dumps(args, sort_keys=True)
        if key in self._done:
            return {"duplicate_ignored": True, "previous_result": self._done[key]}
        self._done[key] = self.inner.call(name, args)
        return self._done[key]


created = []
raw = ToolRegistry()


@raw.register("create_event", "Create an event (side effect!)", title=str, date=str)
def create_event(title: str, date: str) -> dict:
    created.append(title)
    return {"created": True, "title": title, "date": date}


def forgetful(prompt, system):
    if "duplicate_ignored" in prompt:
        return '{"final": "Your standup is booked for 2026-10-19."}'
    return '{"tool": "create_event", "args": {"title": "Standup", "date": "2026-10-19"}}'  # asks twice


def main() -> None:
    trace = Trace("Tool-use loop — exercise solution")
    r = ToolLoop(MockLLM(forgetful), IdempotentTools(raw, {"create_event"}), max_steps=5).run(
        "Book standup on 2026-10-19", trace=trace)
    trace.note(f"events actually created: {len(created)}")
    trace.print()
    assert r.stop_reason == "final" and created == ["Standup"]


if __name__ == "__main__":
    main()
