# Solution — 6. ReAct

**Exercise.** Flag final answers that contain names or numbers no Observation supports.

**Approach.** Collect all Observation lines from the scratchpad and extract the answer's "claims": capitalised words and numbers. Any claim absent from the observations is unsupported.

```python
CLAIM = re.compile(r"\b(?:[A-Z][a-z]+|\d+(?:\.\d+)?)\b")

def ungrounded_claims(result: ReActResult) -> list[str]:
    observed = " ".join(line for step in result.scratchpad for line in step.splitlines()
                        if line.startswith("Observation:"))
    return [c for c in CLAIM.findall(result.answer or "") if c not in observed]
```

Run: `python3 code/patterns/react/exercise_solution.py`

<!-- expected-output: code/patterns/react/exercise_solution.py -->
```text
ReAct — exercise solution
=========================
[tool-using run] answer='Lisbon — currently 21°C and sunny.' grounded=True
[from-memory run] answer='Berlin — 18°C and cloudy.' grounded=False unsupported=['Berlin', '18']
```

**Discussion.** This is a heuristic, and both kinds of error are possible. A legitimate word like "Currently" at the start of a sentence would be flagged, and a claim phrased in lower case would slip through. It is still valuable as a *tripwire*: an answer with zero observed support (the lazy run) is caught with certainty. For higher stakes, require the model to cite observation numbers and check them, the same move [agentic RAG](../part-2-single-agent/10-agentic-rag.md) makes with document ids.
