"""Guardrailed generation: generate -> validate (deterministic code) -> repair, with a
hard repair budget and a safe fallback.

Canonical module: the support-triage capstone imports this file; nothing else in the
repository re-implements it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agentkit import LLM, Trace, extract_json

# A validator receives the *parsed* output and returns a list of human-readable errors.
Validator = Callable[[Any], list[str]]


@dataclass
class GuardResult:
    ok: bool
    value: Any
    attempts: int
    errors: list[list[str]] = field(default_factory=list)  # errors per attempt
    used_fallback: bool = False


# --- Reusable validators -----------------------------------------------------------

def _type_name(t) -> str:
    return " or ".join(x.__name__ for x in t) if isinstance(t, tuple) else t.__name__


def require_fields(**types) -> Validator:
    """``require_fields(reply=str, refund=(int, float))`` — presence and type checks."""

    def check(v: Any) -> list[str]:
        if not isinstance(v, dict):
            return ["output must be a JSON object"]
        errs = [f"missing field '{k}'" for k in types if k not in v]
        errs += [f"field '{k}' must be {_type_name(t)}" for k, t in types.items()
                 if k in v and not isinstance(v[k], t)]
        return errs
    return check


def max_words(key: str, n: int) -> Validator:
    def check(v: Any) -> list[str]:
        words = len(str(v.get(key, "")).split()) if isinstance(v, dict) else 0
        return [f"'{key}' has {words} words (max {n})"] if words > n else []
    return check


def forbid_pattern(key: str, pattern: str, message: str) -> Validator:
    rx = re.compile(pattern)

    def check(v: Any) -> list[str]:
        return [message] if isinstance(v, dict) and rx.search(str(v.get(key, ""))) else []
    return check


def max_value(key: str, limit: float, message: str) -> Validator:
    def check(v: Any) -> list[str]:
        val = v.get(key, 0) if isinstance(v, dict) else 0
        return [message.format(value=val, limit=limit)] if isinstance(val, (int, float)) and val > limit else []
    return check


def one_of(key: str, allowed: set[str]) -> Validator:
    def check(v: Any) -> list[str]:
        val = v.get(key) if isinstance(v, dict) else None
        return [f"'{key}' must be one of {sorted(allowed)}"] if val not in allowed else []
    return check


CARD_NUMBER = r"\b(?:\d[ -]?){13,16}\b"


# --- The loop ------------------------------------------------------------------------

def guarded_generate(
    llm: LLM,
    prompt: str,
    validators: list[Validator],
    *,
    system: str = "",
    max_repairs: int = 2,
    fallback: Optional[Any] = None,
    parse: Callable[[str], Any] = extract_json,
    trace: Optional[Trace] = None,
) -> GuardResult:
    history: list[list[str]] = []
    ask = prompt
    for attempt in range(1, max_repairs + 2):  # 1 initial try + max_repairs repairs
        raw = llm.complete(ask, system=system)
        try:
            value = parse(raw)
            errors = [e for check in validators for e in check(value)]
        except ValueError as exc:
            value, errors = None, [f"unparseable output: {exc}"]
        history.append(errors)
        if trace:
            trace.step(f"attempt {attempt}", "valid" if not errors else "INVALID: " + "; ".join(errors))
        if not errors:
            return GuardResult(True, value, attempt, history)
        # Targeted repair: show the model its own output and the exact failures.
        ask = (
            f"{prompt}\n\nREPAIR. Your previous output was:\n{raw}\n"
            "It failed these checks:\n" + "\n".join(f"- {e}" for e in errors) +
            "\nReturn a corrected output that passes every check."
        )
    if trace:
        trace.step("fallback", json.dumps(fallback, ensure_ascii=False) if fallback is not None else "none — raise to caller")
    return GuardResult(False, fallback, max_repairs + 1, history, used_fallback=True)
