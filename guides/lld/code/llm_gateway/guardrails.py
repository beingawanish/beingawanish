"""Guardrail hooks, run as a chain on the way in and on the way out.

Each guardrail may pass text through, rewrite it (redaction), or stop the
request with GuardrailViolationError (blocked content). GuardrailChain is
itself a Guardrail, so a chain can nest inside another chain.
"""
import re
from abc import ABC
from collections.abc import Iterable, Mapping
from dataclasses import replace

from .errors import GuardrailViolationError
from .models import ChatRequest, Message

DEFAULT_PII_PATTERNS: Mapping[str, str] = {
    "EMAIL": r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+",
    "CARD": r"\b(?:\d[ -]?){13,16}\b",
    "PHONE": r"\+?\d[\d -]{8,}\d",
}


class Guardrail(ABC):
    """Both hooks default to pass-through; a subclass overrides what it needs."""

    name = "guardrail"

    def check_request(self, request: ChatRequest) -> ChatRequest:
        return request

    def check_response(self, text: str) -> str:
        return text


class PiiRedactionGuardrail(Guardrail):
    name = "pii-redaction"

    def __init__(self, patterns: Mapping[str, str] = DEFAULT_PII_PATTERNS) -> None:
        self._patterns = [(label, re.compile(rx)) for label, rx in patterns.items()]

    def redact(self, text: str) -> str:
        for label, pattern in self._patterns:
            text = pattern.sub(f"[{label}]", text)
        return text

    def check_request(self, request: ChatRequest) -> ChatRequest:
        messages = tuple(Message(m.role, self.redact(m.content)) for m in request.messages)
        return replace(request, system=self.redact(request.system), messages=messages)

    def check_response(self, text: str) -> str:
        return self.redact(text)


class BlockedContentGuardrail(Guardrail):
    name = "blocked-content"

    def __init__(self, blocked_terms: Iterable[str]) -> None:
        terms = [re.escape(t) for t in blocked_terms if t.strip()]
        self._pattern = re.compile("|".join(terms), re.IGNORECASE) if terms else None

    def _check(self, text: str, where: str) -> None:
        if self._pattern is not None and self._pattern.search(text):
            raise GuardrailViolationError(self.name, f"blocked term in {where}")

    def check_request(self, request: ChatRequest) -> ChatRequest:
        self._check(request.prompt_text(), "request")
        return request

    def check_response(self, text: str) -> str:
        self._check(text, "response")
        return text


class GuardrailChain(Guardrail):
    name = "chain"

    def __init__(self, guardrails: Iterable[Guardrail] = ()) -> None:
        self._guardrails = tuple(guardrails)

    def check_request(self, request: ChatRequest) -> ChatRequest:
        for guardrail in self._guardrails:
            request = guardrail.check_request(request)
        return request

    def check_response(self, text: str) -> str:
        for guardrail in self._guardrails:
            text = guardrail.check_response(text)
        return text
