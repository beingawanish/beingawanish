"""Tool-use loop demo: a calendar agent recovers from a bad argument, asks before a
side effect, and a runaway agent is stopped by the step limit.

Run:  python3 code/patterns/tool_use_loop/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, ToolRegistry, Trace  # noqa: E402
from patterns.tool_use_loop.loop import ToolLoop  # noqa: E402

CALENDAR = {"2026-10-16": [{"title": "Design review", "start": "13:00", "end": "14:00"}]}
CREATED: list[dict] = []

tools = ToolRegistry()


@tools.register("list_events", "Events on a date (YYYY-MM-DD)", date=str)
def list_events(date: str) -> list:
    return CALENDAR.get(date, [])


@tools.register("create_event", "Create an event (side effect!)", title=str, date=str, start=str, end=str)
def create_event(title: str, date: str, start: str, end: str) -> dict:
    ev = {"title": title, "date": date, "start": start, "end": end}
    CREATED.append(ev)
    CALENDAR.setdefault(date, []).append(ev)
    return {"created": True, **ev}


def calendar_model(prompt: str, system: str) -> str:
    if "Summarise my week" in prompt:  # a runaway: never decides it is done
        return '{"tool": "list_events", "args": {"date": "2026-10-16"}}'
    if '"created": true' in prompt:
        return '{"final": "Booked Sync with Dana on 2026-10-16, 14:00-14:30 (after your design review)."}'
    if "Design review" in prompt:
        return ('{"tool": "create_event", "args": {"title": "Sync with Dana", "date": "2026-10-16", '
                '"start": "14:00", "end": "14:30"}}')
    if "must be str" in prompt:
        return '{"tool": "list_events", "args": {"date": "2026-10-16"}}'
    return '{"tool": "list_events", "args": {"date": 20261016}}'  # wrong type on the first try


def main() -> None:
    llm = MockLLM(calendar_model)
    approvals = []

    def confirm(name, args):  # stands in for a UI prompt to the user
        approvals.append(name)
        return True

    agent = ToolLoop(llm, tools, max_steps=6, require_confirm=frozenset({"create_event"}), confirm=confirm)
    trace = Trace("Tool-use loop")
    trace.note("-- Book a 30-minute sync with Dana tomorrow afternoon (2026-10-16)")
    r1 = agent.run("Book a 30-minute sync with Dana tomorrow afternoon (2026-10-16)", trace=trace)
    trace.note(f"result: {r1.stop_reason} in {r1.steps} steps; confirmations asked: {approvals}")
    trace.note("-- Summarise my week")
    r2 = ToolLoop(llm, tools, max_steps=3).run("Summarise my week", trace=trace)
    trace.note(f"result: {r2.stop_reason}, final={r2.final}")
    trace.print()

    assert r1.stop_reason == "final" and r1.steps == 4 and len(CREATED) == 1
    assert r2.stop_reason == "max_steps" and r2.final is None


if __name__ == "__main__":
    main()
