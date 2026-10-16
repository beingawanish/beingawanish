"""Agentic RAG demo: a question that needs a reformulated query, one that needs no
retrieval at all, and one the corpus cannot answer (abstain).

Run:  python3 code/patterns/agentic_rag/main.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import MockLLM, Trace, rules  # noqa: E402
from patterns.agentic_rag.rag import Retriever, agentic_rag  # noqa: E402

DOCS = {
    "billing-monthly": "Monthly plans: cancel anytime in Settings. No refund is given for a partial month.",
    "billing-downgrade": "If you cancel or downgrade a plan, no refund is issued for unused credit; it stays on "
                         "the account.",
    "billing-annual": "Annual plans get a full refund within 30 days of purchase. After 30 days, the unused months "
                      "are prorated.",
    "security-sso": "SSO with SAML is available on the Enterprise plan.",
    "data-export": "Export all your data from Settings > Privacy > Export; a download link arrives by email.",
}

Q_REFUND = "Can I get a refund on my annual plan after 6 weeks?"
Q_DIRECT = "How do you say 'thank you' in Portuguese?"
Q_ONPREM = "Do you offer an on-premise deployment?"

model = MockLLM(rules([
    # Route decisions.
    (lambda p, s: p.startswith("ROUTE") and "Portuguese" in p, "DIRECT"),
    (lambda p, s: p.startswith("ROUTE"), "RETRIEVE"),
    (lambda p, s: p.startswith("ANSWER directly"), "Obrigado (or obrigada, depending on the speaker)."),
    # Query writing — reformulates using what the grader said was missing.
    (lambda p, s: p.startswith("QUERY") and "annual" in p.split("Still missing:")[1], "annual plan refund after 30 days"),
    (lambda p, s: p.startswith("QUERY") and "annual plan" in p, "cancel plan refund"),
    (lambda p, s: p.startswith("QUERY") and "self-hosted" in p, "enterprise deployment options"),
    (lambda p, s: p.startswith("QUERY") and "on-premise deployment'" in p, "self-hosted installation"),
    (lambda p, s: p.startswith("QUERY"), "on-premise deployment"),
    # Grading.
    (lambda p, s: p.startswith("GRADE") and "[billing-annual]" in p,
     '{"relevant": ["billing-annual"], "sufficient": true, "missing": ""}'),
    (lambda p, s: p.startswith("GRADE") and "refund" in p,
     '{"relevant": [], "sufficient": false, "missing": "the refund rule for annual plans specifically"}'),
    (lambda p, s: p.startswith("GRADE"),
     '{"relevant": [], "sufficient": false, "missing": "anything about on-premise or self-hosted deployment"}'),
    # Answering from evidence.
    (lambda p, s: p.startswith("ANSWER using"),
     "Not a full refund: the full-refund window is 30 days. At 6 weeks you'd get a prorated refund for the "
     "unused months [billing-annual]."),
]))


def main() -> None:
    retriever = Retriever(DOCS)
    trace = Trace("Agentic RAG")
    results = []
    for q in (Q_REFUND, Q_DIRECT, Q_ONPREM):
        trace.note(f"-- {q}")
        r = agentic_rag(model, retriever, q, trace=trace)
        results.append(r)
        trace.note(f"result: {r.stop_reason}; queries={len(r.queries)}; citations={r.citations}")
    trace.note(f"model calls: {model.usage.calls}")
    trace.print()

    assert [r.stop_reason for r in results] == ["answered", "direct", "abstained"]
    assert results[0].citations == ["billing-annual"] and len(results[0].queries) == 2


if __name__ == "__main__":
    main()
