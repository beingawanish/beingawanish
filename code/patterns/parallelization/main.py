"""Parallelization demo: sectioning (three independent checks) and voting (three judges).

Run:  python3 code/patterns/parallelization/main.py
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, extract_json, rules  # noqa: E402
from patterns.parallelization.fanout import fan_out, majority_vote  # noqa: E402

LATENCY = 0.15  # simulated seconds per model call, so the speed-up is real and measurable


def slow(responder):
    def wrapped(prompt, system):
        time.sleep(LATENCY)
        return responder(prompt, system)
    return wrapped


checker = MockLLM(slow(rules([
    ("check tone", '{"pass": true, "note": "warm and professional"}'),
    ("check policy", '{"pass": false, "note": "promises a refund above the $50 agent limit"}'),
    ("check facts", '{"pass": true, "note": "order number and dates match the record"}'),
])))

judge = MockLLM(slow(rules([
    ("judge A", "PHISHING"),
    ("judge B", "PHISHING"),
    ("judge C", "I'm not sure, it could be either."),  # an unusable vote
])))

DRAFT = "Hi Sam, so sorry about order #4471. I've issued a full $120 refund today."
EMAIL = "Your account is locked! Verify your password at http://acme-support.co/login now."


def sectioning(trace: Trace) -> bool:
    checks = {
        name: (lambda n=name: extract_json(checker.complete(f"Check {n} of this reply:\n{DRAFT}")))
        for name in ("tone", "policy", "facts")
    }
    start = time.perf_counter()
    branches = fan_out(checks)
    wall = time.perf_counter() - start
    for b in branches:
        trace.step(f"check:{b.name}", f"pass={b.value['pass']} — {b.value['note']}")
    approved = all(b.ok and b.value["pass"] for b in branches)  # fail closed
    trace.step("fan-in", f"approved={approved}")
    trace.step("timing", f"parallel faster than sequential: {wall < LATENCY * len(checks) * 0.8}")
    return approved


def voting(trace: Trace):
    judges = {j: (lambda j=j: judge.complete(f"You are judge {j}. Is this email PHISHING or SAFE?\n{EMAIL}"))
              for j in ("A", "B", "C")}
    branches = fan_out(judges)
    votes = []
    for b in branches:
        label = b.value.strip().upper()
        usable = label in ("PHISHING", "SAFE")
        trace.step(f"judge:{b.name}", label if usable else f"discarded ({b.value!r})")
        if usable:
            votes.append(label)
    winner, agreement = majority_vote(votes)
    trace.step("fan-in", f"verdict={winner} agreement={agreement:.2f} from {len(votes)} usable votes")
    return winner


def main() -> None:
    trace = Trace("Parallelization")
    trace.note("-- sectioning: three independent guardrail checks on a draft reply")
    approved = sectioning(trace)
    trace.note("-- voting: three judges on one email")
    verdict = voting(trace)
    trace.print()

    assert approved is False  # the policy branch blocks the draft
    assert verdict == "PHISHING"


if __name__ == "__main__":
    main()
