# Solution — 2. Routing

**Exercise.** Accept `"Billing "` and `"TECHNICAL"` as valid routes; keep rejecting unknown ones like `"Sales"`.

**Approach.** Normalise *before* validation, and change nothing else. `Router.parse()` is the hook for exactly this:

```python
class NormalisingRouter(Router):
    def parse(self, raw):
        route, conf = super().parse(raw)
        return route.strip().lower(), conf  # still validated against ROUTES afterwards
```

Run: `python3 code/patterns/routing/exercise_solution.py`

<!-- expected-output: code/patterns/routing/exercise_solution.py -->
```text
Routing — exercise solution
===========================
[I was charged twice.] before=general (fallback)  after=billing (llm)
[App crashes on start.] before=general (fallback)  after=technical (llm)
[Partnership enquiry.] before=general (fallback)  after=general (fallback)
```

**Discussion.** The order matters: normalise, *then* check membership in the route set. Fuzzy matching ("bill" → billing) would go too far, because it starts guessing on the model's behalf, and a guessed route is an unvalidated route. If a model often emits near-miss labels, fix the classifier prompt (list the exact labels, give examples) and measure it in the [eval harness](../part-4-cross-cutting/21-eval-harness.md). Normalisation is a safety net, not a substitute.

*Note on the mock:* the first version of this exercise's mock used the bare trigger `"crashes"`, which also matched the route menu inside every classifier prompt, so *"Partnership enquiry"* was routed to `technical`. `verify.py` caught it. Real-model analogue: prompts that include your label descriptions can leak those words into classification. That is one reason to evaluate on held-out inputs.
