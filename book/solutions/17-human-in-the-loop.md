# Solution — 17. Human-in-the-loop

**Exercise.** Require two different approvers for refunds above $500.

**Approach.** Subclass `ReviewQueue` and override `decide`. For large refunds, approvals accumulate in a set of reviewer names, and the request only becomes `approved` at two distinct names. A rejection by anyone rejects immediately.

```python
class DualControlQueue(ReviewQueue):
    def decide(self, rid, verdict, reviewer, edits=None, note=""):
        req = self.get(rid)
        needs_two = req["action"]["kind"] == "refund" and req["action"]["payload"]["amount"] > self.threshold
        if not needs_two or verdict == "reject":
            return super().decide(rid, verdict, reviewer, edits, note)
        approvals = req.setdefault("approvals", [])
        if reviewer not in approvals:
            approvals.append(reviewer)
        self._save()
        if len(approvals) >= 2:
            super().decide(rid, verdict, reviewer, edits, f"approved by {' + '.join(approvals)}")
```

Run: `python3 code/patterns/human_in_the_loop/exercise_solution.py`

<!-- expected-output: code/patterns/human_in_the_loop/exercise_solution.py -->
```text
Human-in-the-loop — exercise solution
=====================================
[maya approves] status=pending approvals=['maya']
[maya approves] status=pending approvals=['maya']
[omar approves] status=approved approvals=['maya', 'omar']
[resume] executed
ledger: ['refund $900']
```

**Discussion.** Approvals persist with the request, so the two reviewers can act in different processes on different days. In production the reviewer identity must come from authentication, not a free-text field, or dual control is theatre. Also decide what an *edit* by the second approver means: the safest rule is that an edit resets the approvals.
