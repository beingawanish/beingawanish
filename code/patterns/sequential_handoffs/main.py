"""Sequential handoffs demo: one customer conversation passes from triage to billing to
technical support; a second conversation ping-pongs and is escalated.

Run:  python3 code/patterns/sequential_handoffs/main.py
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from patterns.sequential_handoffs.handoff import Agent, HandoffRuntime  # noqa: E402


def last_user(prompt):
    return [ln for ln in prompt.splitlines() if ln.startswith("USER: ")][-1]


def triage(prompt, system):
    u = last_user(prompt)
    if "plan" in u:
        return json.dumps({"handoff_to": "billing", "reason": "plan change", "summary": "Wants to change plan; also login."})
    return json.dumps({"handoff_to": "billing", "reason": "billing issue",
                       "summary": "Customer reports a duplicate March charge."})


def billing(prompt, system):
    u = last_user(prompt)
    if "plan" in u:
        return json.dumps({"handoff_to": "account", "reason": "plans are account settings",
                           "summary": "Plan change requested."})
    if "crash" in u:
        return json.dumps({"handoff_to": "technical", "reason": "app crash",
                           "summary": "Duplicate March charge already refunded. Now: app crashes opening Reports."})
    return json.dumps({"reply": "Found it — the duplicate March charge is refunded; expect it in 3-5 days."})


def account(prompt, system):
    return json.dumps({"handoff_to": "billing", "reason": "plan changes affect invoices",
                       "summary": "Plan change requested."})


def technical(prompt, system):
    u = last_user(prompt)
    if "fixed" in u:
        return json.dumps({"reply": "Glad to hear it! Your refund is still on its way. Anything else?"})
    ctx = "I can see billing already refunded your duplicate charge. " if "refunded" in prompt else ""
    return json.dumps({"reply": ctx + "The Reports crash is fixed in 3.2.1 — please update and reopen."})


AGENTS = {
    "triage": Agent("triage", MockLLM(triage), "Route; never solve.", frozenset({"billing", "technical", "account"})),
    "billing": Agent("billing", MockLLM(billing), "Charges and refunds.", frozenset({"technical", "account"})),
    "account": Agent("account", MockLLM(account), "Login and profile.", frozenset({"billing", "technical"})),
    "technical": Agent("technical", MockLLM(technical), "Bugs and crashes.", frozenset({"billing"})),
}


def main() -> None:
    rt = HandoffRuntime(AGENTS, entry="triage")
    trace = Trace("Sequential handoffs")
    trace.note("-- conversation 1")
    c1 = rt.start()
    for msg in ["Hi, I was charged twice for March.",
                "Thanks! Also the app crashes when I open Reports.",
                "Updated — that fixed it."]:
        trace.step("user", msg)
        rt.user_says(c1, msg, trace)
    trace.note(f"owner now: {c1.owner}; handoffs: {' → '.join(['triage'] + [h.target for h in c1.handoffs])}")
    trace.note("-- conversation 2")
    c2 = rt.start()
    trace.step("user", "Can you change my plan and fix my login?")
    rt.user_says(c2, "Can you change my plan and fix my login?", trace)
    trace.note(f"escalated: {c2.escalated}")
    trace.print()

    assert c1.owner == "technical" and len(c1.handoffs) == 2 and not c1.escalated
    assert c2.escalated


if __name__ == "__main__":
    main()
