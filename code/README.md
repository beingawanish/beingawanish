# Companion code — Agentic Design Patterns

Python 3.10+, standard library only, offline. There are no credentials and no `pip install`.

```
python3 code/verify.py                 # run every example, exercise solution and capstone; check outputs
python3 code/verify.py routing         # just one pattern
python3 code/patterns/routing/main.py  # run one example directly
```

| Path | What |
|---|---|
| `agentkit/` | The shared kernel: `MockLLM` (deterministic, rule-driven), `ToolRegistry`, `Trace`. Patterns depend only on `complete(prompt, system="")`. |
| `patterns/<slug>/` | One pattern each: implementation module, `main.py` demo, `expected_output.txt`, README, `exercise_solution.py`. |
| `capstones/<name>/` | Spec-first `brief.md`, glue code that imports pattern modules, fixtures, `main.py` with acceptance checks. |
| `tools/` | `gen_readmes.py` (pattern READMEs from metadata and expected output); `sync_book_outputs.py` (fills console blocks in the book from expected output). |
| `verify.py` | The single gate: exit codes, byte-for-byte output, README drift, book-quote drift. |

To use a real model, implement `complete(prompt, system="") -> str` (see the docstring in `agentkit/llm.py`) and pass it wherever an example passes a `MockLLM`.
