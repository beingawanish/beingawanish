"""Runnable slice: python3 -m llm_gateway

Two fake providers, a frozen clock and a seeded RNG, so the output is the
same on every run. print() is allowed here and nowhere else in the package.
"""
import itertools
import logging
import random

from . import (
    BlockedContentGuardrail,
    ChatRequest,
    FakeClock,
    FakeProvider,
    GatewayError,
    GuardrailChain,
    LLMGateway,
    Message,
    PiiRedactionGuardrail,
    ProviderOverloadedError,
)


def ask(team: str, text: str, **route: str) -> ChatRequest:
    return ChatRequest(team=team, messages=(Message("user", text),), max_tokens=64, **route)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="  [log] %(message)s")
    clock = FakeClock()
    alpha = FakeProvider("alpha", clock, latency_s=0.4)
    beta = FakeProvider("beta", clock, latency_s=0.6)
    counter = itertools.count(1)
    gateway = LLMGateway(
        {"alpha": alpha, "beta": beta},
        clock=clock,
        guardrail=GuardrailChain([BlockedContentGuardrail(["drop table"]),
                                  PiiRedactionGuardrail()]),
        rng=random.Random(7),
        id_factory=lambda: f"req-{next(counter)}",
    )

    r = gateway.complete(ask("search", "Rank these three results.", model="smart"))
    print(f"1 {r.request_id}: {r.provider}/{r.model} -> {r.text!r} ${r.cost_usd}")

    r = gateway.complete(ask("search", "Rank   these three results. ", model="smart"))
    print(f"2 {r.request_id}: cached={r.cached} cost=${r.cost_usd}")

    alpha.fail_next(*[ProviderOverloadedError("529 overloaded")] * 3)
    r = gateway.complete(ask("search", "Review this diff.", task="code-review"))
    print(f"3 {r.request_id}: fell back past {list(r.fallbacks)} to {r.provider}/{r.model}")

    r = gateway.complete(ask("support", "Email me at jo@example.com", model="smart"))
    print(f"4 {r.request_id}: tier-capped to {r.model}; reply {r.text!r}")

    try:
        gateway.complete(ask("support", "please DROP TABLE users", model="fast"))
    except GatewayError as err:
        print(f"5 refused: {type(err).__name__}: {err}")

    for team in ("search", "support"):
        print(f"  {team}: {gateway.ledger.total_tokens(team)} tokens,"
              f" ${gateway.ledger.total_cost(team)},"
              f" budget left {gateway.quotas.budget_remaining(team)}")


if __name__ == "__main__":
    main()
