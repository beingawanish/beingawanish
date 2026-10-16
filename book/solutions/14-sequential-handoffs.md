# Solution — 14. Sequential handoffs

**Exercise.** Give an agent one chance to correct an invalid handoff target, without modifying the runtime.

**Approach.** Wrap the agent's model. If its reply names a target outside the allowed set, re-ask once with the valid targets appended; otherwise pass the reply through. The runtime still enforces the graph, so a second invalid target escalates as before.

```python
class GraphAwareLLM:
    def __init__(self, inner, allowed: frozenset[str]):
        self.inner, self.allowed, self.corrections = inner, allowed, 0

    def complete(self, prompt, system=""):
        raw = self.inner.complete(prompt, system)
        target = extract_json(raw).get("handoff_to")
        if target is None or target in self.allowed:
            return raw
        self.corrections += 1
        return self.inner.complete(f"{prompt}\nCORRECTION: '{target}' does not exist. "
                                   f"Valid targets: {sorted(self.allowed)}.", system)
```

Run: `python3 code/patterns/sequential_handoffs/exercise_solution.py`

<!-- expected-output: code/patterns/sequential_handoffs/exercise_solution.py -->
```text
Sequential handoffs — exercise solution
=======================================
-- without correction
[escalate] technical tried to hand off to 'refunds' (not allowed)
escalated=True, owner=technical
-- with correction
[technical ⇒ billing] refund request | summary: Wants refund for outage.
[billing] Per our SLA I've applied a one-day service credit to your next invoice.
escalated=False, owner=billing
```

**Discussion.** This is the repair idea from [guardrailed generation](../part-2-single-agent/11-guardrailed-generation.md) applied to a handoff: a precise error plus one retry, then the hard rule. Count corrections per agent. An agent that needs them often has a scope description that does not match the graph.
