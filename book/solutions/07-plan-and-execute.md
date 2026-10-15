# Solution — 7. Plan-and-execute

**Exercise.** Repair a failed availability check in code, using venues from the earlier search, so that the planner is not called.

**Approach.** Use the `repair` hook. It sees the failed step, the remaining plan and all results. When the failure is an availability check and an untried venue exists, it returns a new remaining plan: re-check with the next venue, then the old remaining steps with the venue swapped in. Otherwise it returns `None` and the planner decides.

```python
def next_venue_repair(step, result, remaining, results):
    if step.action != "check_availability":
        return None
    candidates = next((r.output for r in results.values() if isinstance(r.output, list)), [])
    tried = {r.note.removesuffix(" unavailable") for r in results.values() if r.note.endswith("unavailable")}
    nxt = next((v for v in candidates if v not in tried), None)
    if nxt is None:
        return None  # nothing local to try: let the planner think
    old = step.args["venue"]
    retry = Step(step.id + "r", "check_availability", {**step.args, "venue": nxt}, "local repair")
    swapped = [replace(s, id=s.id + "r", args={k: (nxt if v == old else v) for k, v in s.args.items()})
               for s in remaining]
    return [retry, *swapped]
```

Run: `python3 code/patterns/plan_and_execute/exercise_solution.py`

<!-- expected-output: code/patterns/plan_and_execute/exercise_solution.py -->
```text
Plan-and-execute — exercise solution
====================================
[plan v1] s1:search_venues → s2:check_availability → s3:get_quote → s4:draft_invite
[exec s1] ok  ['Casa Azul', 'Quinta Verde']
[exec s2] FAIL booked (Casa Azul unavailable)
[local repair] s2r:check_availability → s3r:get_quote → s4r:draft_invite
[exec s2r] ok  free
[exec s3r] ok  EUR 1800
[exec s4r] ok  Invite: offsite at Quinta Verde on 14 Nov
result: completed; replans=0; planner calls=1 (was 2)
```

**Discussion.** The repair is deliberately narrow. It handles one failure type with an obvious mechanical fix and declines everything else. A repair hook that tries to be clever becomes a second, worse planner. Note the step ids get an `r` suffix, so the audit trail shows which steps came from repair rather than from a plan version.
