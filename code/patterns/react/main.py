"""ReAct demo: a multi-hop question where an empty search forces a rethink, and an
unanswerable question stopped by the repeated-action guard.

Run:  python3 code/patterns/react/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, ToolRegistry, Trace  # noqa: E402
from patterns.react.react import react  # noqa: E402

FACTS = {
    "orbit x1": "Orbit X1 is a VR headset made by Lumen Labs.",
    "lumen labs": "Lumen Labs is headquartered in Lisbon, Portugal.",
}
WEATHER = {"lisbon": "Lisbon: 21°C, sunny"}

tools = ToolRegistry()


@tools.register("search", "Look up a short encyclopedia fact", q=str)
def search(q: str) -> str:
    hits = [v for k, v in FACTS.items() if k == q.lower().strip()]
    return hits[0] if hits else "No results."


@tools.register("weather", "Current weather for a city", q=str)
def weather(q: str) -> str:
    return WEATHER.get(q.lower(), f"No weather data for {q}.")


# The mock "reasons" from the scratchpad: it decides by what it has observed so far.
def model(prompt: str, system: str) -> str:
    q = prompt.split("Question: ", 1)[1]
    if "shoe size" in q:
        return "Thought: I should search for the CEO's shoe size.\nAction: search[Lumen Labs CEO shoe size]"
    if "Lisbon: 21" in q:
        return "Thought: I have the city and its weather.\nFinal Answer: Lisbon — currently 21°C and sunny."
    if "headquartered in Lisbon" in q:
        return "Thought: The HQ is Lisbon; now get the weather there.\nAction: weather[Lisbon]"
    if "made by Lumen Labs" in q:
        return "Thought: The maker is Lumen Labs; find where it is headquartered.\nAction: search[Lumen Labs]"
    if "No results." in q:
        return "Thought: The phrase was too specific; search the product name alone.\nAction: search[Orbit X1]"
    return "Thought: First find who makes the Orbit X1 headset.\nAction: search[Orbit X1 headset maker]"


def main() -> None:
    llm = MockLLM(model)
    trace = Trace("ReAct")
    trace.note("-- Q1: What's the weather at the HQ of the company that makes the Orbit X1?")
    r1 = react(llm, tools, "What's the weather at the HQ of the company that makes the Orbit X1?", trace=trace)
    trace.note(f"result: {r1.stop_reason} in {r1.steps} steps")
    trace.note("-- Q2: What is the Lumen Labs CEO's shoe size?")
    r2 = react(llm, tools, "What is the Lumen Labs CEO's shoe size?", trace=trace)
    trace.note(f"result: {r2.stop_reason} after {r2.steps} steps, answer={r2.answer}")
    trace.note(f"model calls: {llm.usage.calls}")
    trace.print()

    assert r1.answer and "21°C" in r1.answer and r1.steps == 5
    assert r2.answer is None and r2.stop_reason == "repeated_action"


if __name__ == "__main__":
    main()
