"""Exercise solution — Reflection.

Task: self-critique missed the leap-year February bug in days_in_month. Add
*trajectory* reflection (Reflexion-style): when a later check reveals a failure, the
model writes a one-line lesson; lessons are stored and prepended (as system text)
to future tasks. Show the next, related task benefits.

Run:  python3 code/patterns/reflection/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.reflection.reflect import reflect  # noqa: E402

GOOD = ("def days_left(m, d, y):\n"
        "    feb = 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28\n"
        "    return [31, feb, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1] - d")
BAD = "def days_left(m, d, y):\n    return [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1] - d"

model = MockLLM(rules([
    (lambda p, s: p.startswith("LESSON"), "Lesson: month-length code must handle February in leap years."),
    (lambda p, s: "CRITIQUE" in p, "NO ISSUES"),
    (lambda p, s: "days_left" in p and "leap years" in s, GOOD),   # lesson in context -> better draft
    (lambda p, s: "days_left" in p, BAD),
]))


def passes(src: str) -> bool:
    ns: dict = {}
    exec(src, ns)
    return ns["days_left"](2, 10, 2024) == 19 and ns["days_left"](2, 10, 2023) == 18


def main() -> None:
    trace = Trace("Reflection — exercise solution")
    lessons: list[str] = []
    task = "Write Python days_left(m, d, y): days remaining in the month after day d."

    before = reflect(model, task)
    trace.step("without lessons", f"tests pass={passes(before.output)}")
    if not passes(before.output):  # an outside signal (tests, a user report) reveals the failure
        lessons.append(model.complete(f"LESSON from failure on: {task}"))
        trace.step("stored", lessons[-1])
    after = reflect(model, task, system="\n".join(lessons))
    trace.step("with lessons", f"tests pass={passes(after.output)}")
    trace.print()
    assert not passes(before.output) and passes(after.output)


if __name__ == "__main__":
    main()
