"""Context management demo: a long on-call session assembled under a 300-token budget,
compared with the naive "send everything" prompt.

Run:  python3 code/patterns/context_management/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace  # noqa: E402
from agentkit.llm import _tokens as tokens  # noqa: E402
from patterns.context_management.context import ContextManager, naive_prompt  # noqa: E402

SYSTEM = "You are the on-call assistant. RULE: never deploy on Fridays without an approved change ticket."
TASK = "Roll back payments-api to the last good version"
LONG = " ".join(["Detailed flag reference and examples follow for every option."] * 8)
TOOLS = {
    "deploy": ("deploy or roll back a service", "deploy(service, version, ticket). Rollback = deploy previous version. "
               "Requires ticket on Fridays. " + LONG),
    "logs": ("search service logs", "logs(service, query, since). " + LONG),
    "metrics": ("query a metric", "metrics(service, name, window). " + LONG),
    "pager": ("page a human", "pager(team, message). " + LONG),
    "flags": ("toggle feature flags", "flags(name, on). " + LONG),
    "db": ("run read-only SQL", "db(query). " + LONG),
}
TRANSCRIPT = [
    "USER: payments-api error rate jumped at 14:02 (incident INC-4411).",
    "ASSISTANT: Checking logs for payments-api since 14:00.",
    "TOOL: 312 errors 'card_token null' starting 14:02.",
    "ASSISTANT: Errors began right after deploy v2.31.0 at 14:01.",
    "USER: It's Friday — change ticket CHG-881 is approved for a rollback.",
    "ASSISTANT: Noted CHG-881. Last good version is v2.30.4.",
    "TOOL: metrics: p95 latency normal; only error rate affected.",
    "USER: Roll it back please.",
]
DOCS = [
    ("runbook-rollback", 0.92, "Rollback runbook: deploy the previous version with the change ticket; watch errors 10 min."),
    ("postmortem-2025", 0.40, "Old postmortem about a cache stampede in search. " + " ".join(["Timeline entry."] * 20)),
    ("style-guide", 0.10, "Engineering style guide. " + " ".join(["Naming rules."] * 25)),
]

summarizer = MockLLM(lambda p, s: (
    "Incident INC-4411 on payments-api: errors 'card_token null' since 14:02, right after deploy v2.31.0. "
    "Friday; change ticket CHG-881 approved for rollback."), name="small-summarizer", price=(0.25, 1.25))


def main() -> None:
    trace = Trace("Context management")
    naive = tokens(naive_prompt(SYSTEM, TASK, TOOLS, TRANSCRIPT, DOCS))
    cm = ContextManager(budget=300, summarizer=summarizer, keep_recent=3)

    trace.note("-- call 1: nothing loaded yet")
    p1, r1 = cm.assemble(SYSTEM, TASK, TOOLS, set(), TRANSCRIPT, DOCS)
    trace.step("naive prompt", f"{naive} tokens")
    trace.step("managed prompt", f"{r1.total} tokens (budget 300): " + ", ".join(f"{k}={v}" for k, v in r1.sections.items()))
    trace.step("compacted", f"{r1.compacted_turns} old turns → 1 summary ({cm.summarizer_calls} summarizer call)")
    trace.step("evicted", ", ".join(r1.evicted_docs))

    trace.note("-- call 2: the model asked help(deploy); two more turns happened")
    more = TRANSCRIPT + ["ASSISTANT: help(deploy)", "TOOL: (deploy docs loaded)"]
    p2, r2 = cm.assemble(SYSTEM, TASK, TOOLS, {"deploy"}, more, DOCS)
    trace.step("managed prompt", f"{r2.total} tokens: " + ", ".join(f"{k}={v}" for k, v in r2.sections.items()))
    trace.step("evicted", ", ".join(r2.evicted_docs))
    trace.step("progressive disclosure", f"full docs loaded for {r2.loaded_tool_docs}; other 5 tools stay one-liners")
    trace.step("compacted", f"{r2.compacted_turns} turns folded in total; summarizer calls={cm.summarizer_calls} (incremental)")
    pinned_ok = "never deploy on Fridays" in p2 and "CHG-881" in p2 and "INC-4411" in p2
    trace.step("pinned + recalled", f"rule present={'never deploy on Fridays' in p2}, CHG-881 present={'CHG-881' in p2}, "
                                    f"INC-4411 present={'INC-4411' in p2}")
    trace.print()

    assert r1.total <= 300 and r2.total <= 300 and not r2.over_budget and naive > 2 * r1.total and pinned_ok
    assert r1.evicted_docs == ["postmortem-2025 (relevance 0.40)", "style-guide (relevance 0.10)"]
    assert cm.summarizer_calls == 2


if __name__ == "__main__":
    main()
