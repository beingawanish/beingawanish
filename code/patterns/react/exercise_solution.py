"""Exercise solution — ReAct.

Task: a model can skip the tools and write a confident `Final Answer` from memory.
Write a post-hoc grounding check: every number and capitalised name in the final
answer must appear in some Observation. Show it passing the real run and flagging
an answer made up without tool calls.

Run:  python3 code/patterns/react/exercise_solution.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.react.main import model, tools  # noqa: E402
from patterns.react.react import ReActResult, react  # noqa: E402

CLAIM = re.compile(r"\b(?:[A-Z][a-z]+|\d+(?:\.\d+)?)\b")


def ungrounded_claims(result: ReActResult) -> list[str]:
    observed = " ".join(line for step in result.scratchpad for line in step.splitlines()
                        if line.startswith("Observation:"))
    return [c for c in CLAIM.findall(result.answer or "") if c not in observed]


def main() -> None:
    trace = Trace("ReAct — exercise solution")
    q = "What's the weather at the HQ of the company that makes the Orbit X1?"
    real = react(MockLLM(model), tools, q)
    lazy = react(MockLLM(lambda p, s: "Thought: I remember this.\nFinal Answer: Berlin — 18°C and cloudy."), tools, q)
    for name, r in (("tool-using run", real), ("from-memory run", lazy)):
        bad = ungrounded_claims(r)
        trace.step(name, f"answer={r.answer!r} grounded={not bad}" + (f" unsupported={bad}" if bad else ""))
    trace.print()
    assert ungrounded_claims(real) == [] and ungrounded_claims(lazy) == ["Berlin", "18"]


if __name__ == "__main__":
    main()
