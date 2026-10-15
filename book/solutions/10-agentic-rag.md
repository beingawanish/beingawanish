# Solution — 10. Agentic RAG

**Exercise.** Skip the model's route decision when the question obviously needs the corpus.

**Approach.** The retriever already knows each term's IDF. A question containing a high-IDF corpus term (a word that is rare and therefore distinctive in the corpus, like *annual*) is in-domain, so retrieve without asking. Questions with no such term still go through the route call.

```python
def obviously_in_domain(retriever: Retriever, question: str, min_idf: float = 1.0) -> list[str]:
    return [w for w in tokenize(question) if retriever.idf.get(w, 0) >= min_idf]

r = agentic_rag(model, retriever, q, skip_route=bool(obviously_in_domain(retriever, q)))
```

Run: `python3 code/patterns/agentic_rag/exercise_solution.py`

<!-- expected-output: code/patterns/agentic_rag/exercise_solution.py -->
```text
Agentic RAG — exercise solution
===============================
[skip ROUTE] 'Can I get a refund on my annual plan after 6 weeks?' distinctive terms=['annual'] -> answered, 5 calls
[ask ROUTE] "How do you say 'thank you' in Portuguese?" distinctive terms=[] -> direct, 2 calls
```

**Discussion.** The refund question now takes 5 calls instead of 6, and the Portuguese question is unchanged because it has no distinctive corpus term. The first version of this solution flagged the word *get* as distinctive (it occurs in one document), so `get`, `give` and `say` were added to the stop-word list. That is a reminder that cheap heuristics need their own small eval. The heuristic is one-sided by design: it may only *skip* the route call, never block retrieval.
