# Solution — 16. Critic–reviewer loop

**Exercise.** Turn any test that passed before and fails now into an automatic blocking regression finding.

**Approach.** Wrap the reviewer with memory of every test that has ever passed. Each review computes current results, flags regressions, and adds them to the reviewer's normal findings.

```python
class RegressionAwareReviewer:
    def __init__(self, inner):
        self.inner, self.ever_passed = inner, set()

    def __call__(self, code):
        now = results(code)
        regressions = [i for i in self.ever_passed if not now[i]]
        self.ever_passed |= {i for i, ok in now.items() if ok}
        return self.inner(code) + [Finding(f"R{n}", "blocking", f"REGRESSION: {i!r} passed before, fails now")
                                   for n, i in enumerate(sorted(regressions), 1)]
```

Run: `python3 code/patterns/critic_reviewer/exercise_solution.py`

<!-- expected-output: code/patterns/critic_reviewer/exercise_solution.py -->
```text
Critic–reviewer — exercise solution
===================================
[review 1] F1[blocking] accents are not transliterated; F2[blocking] separators wrong: want single dashes between words, none at ends; F3[nit] add a docstring
[author F1] fixed: addressed → noted
[author F2] fixed: addressed → noted
[author F3] fixed: addressed → noted
[review 2] F2[blocking] separators wrong: want single dashes between words, none at ends; F3[nit] add a docstring; R1[blocking] REGRESSION: 'Hello World' passed before, fails now
[author F2] fixed: addressed → noted
[author F3] fixed: addressed → noted
[author R1] fixed: addressed → noted
[review 3] F3[nit] add a docstring
result: approved=True in 3 rounds
```

**Discussion.** The regressing revision fixed accents but broke `'Hello World'`. Without memory, the reviewer would have reported only the current failures, and the author could have oscillated between two half-fixes indefinitely. Naming the finding `REGRESSION` matters: it tells the author that its last change caused the problem, which is the fastest route to the fix.
