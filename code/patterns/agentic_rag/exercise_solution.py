"""Exercise solution — Agentic RAG.

Task: the ROUTE call ("do we need the knowledge base?") costs a model call on every
question. Make it free when the answer is obvious: if the question contains a
distinctive corpus term (high IDF), skip ROUTE and retrieve directly. Keep the
model's ROUTE decision for everything else. Count the calls saved.

Run:  python3 code/patterns/agentic_rag/exercise_solution.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.agentic_rag.main import DOCS, Q_DIRECT, Q_REFUND, model  # noqa: E402
from patterns.agentic_rag.rag import Retriever, agentic_rag, tokenize  # noqa: E402


def obviously_in_domain(retriever: Retriever, question: str, min_idf: float = 1.0) -> list[str]:
    return [w for w in tokenize(question) if retriever.idf.get(w, 0) >= min_idf]


def main() -> None:
    retriever = Retriever(DOCS)
    trace = Trace("Agentic RAG — exercise solution")
    for q in (Q_REFUND, Q_DIRECT):
        terms = obviously_in_domain(retriever, q)
        before = model.usage.calls
        r = agentic_rag(model, retriever, q, skip_route=bool(terms))
        trace.step("skip ROUTE" if terms else "ask ROUTE", f"{q!r} distinctive terms={terms} -> {r.stop_reason}, "
                   f"{model.usage.calls - before} calls")
    trace.print()
    assert obviously_in_domain(retriever, Q_REFUND) and not obviously_in_domain(retriever, Q_DIRECT)


if __name__ == "__main__":
    main()
