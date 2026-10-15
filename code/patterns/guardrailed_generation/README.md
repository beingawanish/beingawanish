# Pattern 11 — Guardrailed generation

Generate → validate with deterministic code → repair with targeted errors; safe fallback.

| | |
|---|---|
| Implementation | [`guardrails.py`](guardrails.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | — (with its chapter) |
| Chapter | — (written in its assigned part) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/guardrailed_generation/main.py
```

## Expected output

```text
Guardrailed generation
======================
-- ticket #4471: double charge of $45
[attempt 1] INVALID: unparseable output: no JSON found in model output
[attempt 2] INVALID: reply must not contain a card number
[attempt 3] valid
result: ok=True attempts=3 reply='Refunded $45 to your card. Sorry for the trouble!'
-- ticket #5120: wants a full $180 refund
[attempt 1] INVALID: refund 180.0 exceeds the agent limit of 50.0
[attempt 2] INVALID: refund 180.0 exceeds the agent limit of 50.0
[attempt 3] INVALID: refund 180.0 exceeds the agent limit of 50.0
[fallback] {"reply": "Thanks for your patience — a teammate will review your case today.", "refund": 0.0, "tags": ["needs-human"]}
result: ok=False attempts=3 used_fallback=True tags=['needs-human']
```

> **Canonical module.** Built early for the support-triage capstone, which imports it. Its chapter is written in its assigned part.

Verified by `python3 code/verify.py guardrailed_generation`.
