"""Exercise solution — Guardrailed generation.

Task: the CARD_NUMBER regex blocks any 13-16 digit run, so a reply quoting a
16-digit *order* number is rejected and repaired for nothing. Add a Luhn checksum
so only digit runs that could be real card numbers are blocked.

Run:  python3 code/patterns/guardrailed_generation/exercise_solution.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from agentkit import Trace  # noqa: E402
from patterns.guardrailed_generation.guardrails import CARD_NUMBER, forbid_pattern  # noqa: E402


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


REPLIES = {
    "order number": {"reply": "Your order 1234 5678 9012 3456 has shipped."},
    "test card": {"reply": "Charged card 4111 1111 1111 1111."},
}


def main() -> None:
    trace = Trace("Guardrailed generation — exercise solution")
    regex_only = forbid_pattern("reply", CARD_NUMBER, "reply must not contain a card number")
    with_luhn = forbid_card_numbers("reply")
    for name, value in REPLIES.items():
        trace.step(name, f"regex-only blocks={bool(regex_only(value))}  regex+Luhn blocks={bool(with_luhn(value))}")
    trace.print()
    assert regex_only(REPLIES["order number"]) and not with_luhn(REPLIES["order number"])
    assert with_luhn(REPLIES["test card"])


if __name__ == "__main__":
    main()
