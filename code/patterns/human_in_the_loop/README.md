# Pattern 17 — Human-in-the-loop

Pause risky actions at a policy checkpoint, persist state, resume exactly once.

| | |
|---|---|
| Implementation | [`hitl.py`](hitl.py) |
| Demo | [`main.py`](main.py) |
| Exercise solution | — (with its chapter) |
| Chapter | — (written in its assigned part) |

Python 3.10+, standard library only, offline. The model is `agentkit.MockLLM`, so output is deterministic.

## Run

```
python3 code/patterns/human_in_the_loop/main.py
```

## Expected output

```text
Human-in-the-loop
=================
-- process 1 (hour 0): agent proposes actions
[executed] refund {'customer': 'sam', 'amount': 20} auto: no policy rule fired
[pending] refund {'customer': 'lee', 'amount': 140} R001 refund $140 > $100
[pending] close_account {'customer': 'kim'} R002 irreversible action
[pending] refund {'customer': 'ana', 'amount': 35} R003 low confidence 0.55
-- process 2 (hour 3): reviewer works the queue
[pending] R001, R002, R003
[resume R001] executed — edit by maya
[resume R002] rejected — customer has open dispute
[resume R001] already-executed — idempotent: not re-run
-- process 3 (hour 30): nobody decided R003
[expired] R003
[resume R003] expired — default deny
ledger: refund(amount=20, customer=sam) | refund(amount=100, customer=lee)
```

> **Canonical module.** Built early for the support-triage capstone, which imports it. Its chapter is written in its assigned part.

Verified by `python3 code/verify.py human_in_the_loop`.
