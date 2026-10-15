"""Supervisor demo: a pricing brief where the supervisor notices a gap after the writer's
first draft and sends work back — plus a supervisor stopped by loop detection.

Run:  python3 code/patterns/supervisor/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.supervisor.supervisor import Supervisor  # noqa: E402

PRICES = {"Acme (us)": 49, "Beta": 59, "Gamma": 45}


# Workers are agents in their own right; here, small deterministic stand-ins with state.
def researcher(instruction, state):
    state["prices"] = PRICES
    return "Monthly list prices: " + ", ".join(f"{k} ${v}" for k, v in PRICES.items())


def analyst(instruction, state):
    ours = state["prices"]["Acme (us)"]
    state["deltas"] = {k: round((ours - v) / v * 100) for k, v in state["prices"].items() if k != "Acme (us)"}
    return "Acme vs competitors: " + ", ".join(f"{d:+d}% vs {k}" for k, d in state["deltas"].items())


def writer(instruction, state):
    if "deltas" in state:
        return "Acme is priced mid-market: 17% below Beta and 9% above Gamma."
    return "Acme sits between Beta and Gamma on price."


WORKERS = {"researcher": researcher, "analyst": analyst, "writer": writer}
ROLES = {"researcher": "finds facts", "analyst": "computes comparisons", "writer": "drafts prose"}


def boss(prompt, system):
    history = prompt.split("History:\n", 1)[1]
    if "17% below Beta" in history:
        return json.dumps({"next": "FINISH", "final": "Acme is priced mid-market: 17% below Beta and 9% above Gamma."})
    if "vs Beta" in history:
        return json.dumps({"next": "writer", "instruction": "Redraft using the percentage comparison"})
    if "between Beta and Gamma" in history:  # reads the draft, spots the missing numbers
        return json.dumps({"next": "analyst", "instruction": "Compute our price difference vs each competitor in %"})
    if "list prices" in history:
        return json.dumps({"next": "writer", "instruction": "Draft one sentence positioning our price"})
    return json.dumps({"next": "researcher", "instruction": "Collect competitor list prices"})


def stuck_boss(prompt, system):
    return json.dumps({"next": "researcher", "instruction": "Collect competitor list prices"})


def main() -> None:
    llm = MockLLM(boss, name="supervisor-model")
    trace = Trace("Supervisor")
    trace.note("-- Write a one-sentence pricing brief")
    r1 = Supervisor(llm, WORKERS, ROLES).run("Write a one-sentence pricing brief", trace=trace)
    trace.note(f"result: {r1.stop_reason} after {len(r1.turns)} worker turns, {llm.usage.calls} supervisor calls")
    trace.note("-- Same task, a supervisor that repeats itself")
    r2 = Supervisor(MockLLM(stuck_boss), WORKERS, ROLES).run("Write a one-sentence pricing brief", trace=trace)
    trace.note(f"result: ok={r2.ok}, {r2.stop_reason}")
    trace.print()

    assert r1.ok and [w for w, _, _ in r1.turns] == ["researcher", "writer", "analyst", "writer"]
    assert not r2.ok and r2.stop_reason.startswith("loop")


if __name__ == "__main__":
    main()
