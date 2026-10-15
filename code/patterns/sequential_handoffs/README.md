# Pattern 14 — Sequential handoffs

Agents transfer ownership of a live conversation via an explicit handoff object.

| | |
|---|---|
| Implementation | [`handoff.py`](handoff.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | [`exercise_solution.py`](exercise_solution.py) |
| Chapter | [`book/part-3-multi-agent/14-sequential-handoffs.md`](../../../book/part-3-multi-agent/14-sequential-handoffs.md) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/sequential_handoffs/main.py
```

## Expected output

```text
Sequential handoffs
===================
-- conversation 1
[user] Hi, I was charged twice for March.
[triage ⇒ billing] billing issue | summary: Customer reports a duplicate March charge.
[billing] Found it — the duplicate March charge is refunded; expect it in 3-5 days.
[user] Thanks! Also the app crashes when I open Reports.
[billing ⇒ technical] app crash | summary: Duplicate March charge already refunded. Now: app crashes opening Reports.
[technical] I can see billing already refunded your duplicate charge. The Reports crash is fixed in 3.2.1 — please update and reopen.
[user] Updated — that fixed it.
[technical] Glad to hear it! Your refund is still on its way. Anything else?
owner now: technical; handoffs: triage → billing → technical
-- conversation 2
[user] Can you change my plan and fix my login?
[triage ⇒ billing] plan change | summary: Wants to change plan; also login.
[billing ⇒ account] plans are account settings | summary: Plan change requested.
[escalate] ping-pong: triage → billing → account → billing
escalated: True
```

Verified by `python3 code/verify.py sequential_handoffs`.
