# Solution — 11. Guardrailed generation

**Exercise.** Stop the card-number validator rejecting long order numbers.

**Approach.** Keep the regex as a cheap candidate finder, then confirm each candidate with the Luhn checksum that real card numbers satisfy.

```python
def luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0

def forbid_card_numbers(key: str):
    rx = re.compile(CARD_NUMBER)
    def check(v):
        text = str(v.get(key, "")) if isinstance(v, dict) else ""
        hits = [re.sub(r"\D", "", m.group(0)) for m in rx.finditer(text)]
        return ["reply must not contain a card number"] if any(luhn_ok(h) for h in hits) else []
    return check
```

Run: `python3 code/patterns/guardrailed_generation/exercise_solution.py`

<!-- expected-output: code/patterns/guardrailed_generation/exercise_solution.py -->
```text
Guardrailed generation — exercise solution
==========================================
[order number] regex-only blocks=True  regex+Luhn blocks=False
[test card] regex-only blocks=True  regex+Luhn blocks=True
```

**Discussion.** About one random 16-digit number in ten passes Luhn, so some order numbers will still be blocked. The false-positive rate drops tenfold, not to zero. If that matters, add a prefix check (card networks use known IIN ranges) or exempt numbers preceded by "order". The general lesson: a validator is code with its own error rates, so test it on real samples of valid output, not only on the bad cases it was written for.
