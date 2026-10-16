# Solution — 9. Tool-use loop

**Exercise.** Make side-effecting tools idempotent in the host, without changing `ToolLoop`.

**Approach.** Wrap the registry. `ToolLoop` depends only on `specs()` and `call()`, so a wrapper with the same two methods can dedupe calls by `(name, args)` for the named side-effecting tools.

```python
class IdempotentTools(ToolRegistry):
    def __init__(self, inner: ToolRegistry, side_effecting: set[str]):
        super().__init__()
        self.inner, self.side_effecting = inner, side_effecting
        self._done: dict[str, object] = {}

    def specs(self):
        return self.inner.specs()

    def call(self, name, args):
        if name not in self.side_effecting:
            return self.inner.call(name, args)
        key = name + json.dumps(args, sort_keys=True)
        if key in self._done:
            return {"duplicate_ignored": True, "previous_result": self._done[key]}
        self._done[key] = self.inner.call(name, args)
        return self._done[key]
```

Run: `python3 code/patterns/tool_use_loop/exercise_solution.py`

<!-- expected-output: code/patterns/tool_use_loop/exercise_solution.py -->
```text
Tool-use loop — exercise solution
=================================
[call 1] create_event({"title": "Standup", "date": "2026-10-19"})
[result 1] {"created": true, "title": "Standup", "date": "2026-10-19"}
[call 2] create_event({"title": "Standup", "date": "2026-10-19"})
[result 2] {"duplicate_ignored": true, "previous_result": {"created": true, "title": "Standup", "date": "2026-10-19"}}
[final] Your standup is booked for 2026-10-19.
events actually created: 1
```

**Discussion.** Returning `duplicate_ignored` (rather than silently returning the old result) tells the model what happened, and here it is what lets the model conclude it is done. The dedupe window is one run. Across runs, use real idempotency keys at the service, because two *intended* identical bookings on different days are legitimate.
