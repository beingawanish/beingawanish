"""Exercise solution — Routing.

Task: the classifier sometimes answers "Billing " or "TECHNICAL" instead of the exact
route name, and every such answer falls back to `general`. Normalise the label
before validation — but do NOT accept genuinely unknown routes.

Run:  python3 code/patterns/routing/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.routing.main import ROUTES  # noqa: E402
from patterns.routing.router import Router  # noqa: E402


class NormalisingRouter(Router):
    def parse(self, raw):
        route, conf = super().parse(raw)
        return route.strip().lower(), conf  # still validated against ROUTES afterwards


sloppy = MockLLM(rules([
    # Triggers quote the ticket text exactly: the prompt also contains the route menu,
    # so a bare word like "crashes" would match every prompt.
    ("I was charged twice", '{"route": "Billing ", "confidence": 0.93}'),
    ("App crashes on start", '{"route": "TECHNICAL", "confidence": 0.88}'),
    ("Partnership enquiry", '{"route": "Sales", "confidence": 0.90}'),
]))
TICKETS = ["I was charged twice.", "App crashes on start.", "Partnership enquiry."]


def main() -> None:
    trace = Trace("Routing — exercise solution")
    before = Router(sloppy, ROUTES, fallback="general")          # no keyword pre-filter: force LLM path
    after = NormalisingRouter(sloppy, ROUTES, fallback="general")
    for t in TICKETS:
        b, a = before.classify(t), after.classify(t)
        trace.step(t, f"before={b.route} ({b.method})  after={a.route} ({a.method})")
    trace.print()
    assert [after.classify(t).route for t in TICKETS] == ["billing", "technical", "general"]


if __name__ == "__main__":
    main()
