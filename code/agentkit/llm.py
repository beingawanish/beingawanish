"""A deterministic mock LLM.

Real models are stochastic, slow, and need credentials. The examples in this book
need the opposite: the same input must produce the same output on every machine,
offline, so that ``verify.py`` can check results byte for byte.

``MockLLM`` wraps a *responder*: a plain function ``(prompt, system) -> str``.
Most examples build the responder with :func:`rules`, an ordered list of
``(trigger, reply)`` pairs where the first matching trigger wins. That keeps the
"model behaviour" of each example visible in one place, next to the code that
uses it.

To run an example against a real model, implement the same one-method protocol::

    class AnthropicLLM:
        def __init__(self, client, model):
            self.client, self.model = client, model
        def complete(self, prompt: str, system: str = "") -> str:
            msg = self.client.messages.create(
                model=self.model, max_tokens=1024, system=system,
                messages=[{"role": "user", "content": prompt}])
            return msg.content[0].text

Nothing else in the patterns needs to change.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol, Union

Responder = Callable[[str, str], str]
Trigger = Union[str, Callable[[str, str], bool]]
Reply = Union[str, Callable[[str, str], str]]


class LLM(Protocol):
    """The only interface any pattern relies on."""

    def complete(self, prompt: str, system: str = "") -> str: ...


def _tokens(text: str) -> int:
    """Crude, deterministic token estimate: ~0.75 words per token."""
    return max(1, round(len(text.split()) / 0.75))


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Simulated price in USD per 1M tokens (input, output). Illustrative only.
    price_in: float = 3.0
    price_out: float = 15.0

    @property
    def cost_usd(self) -> float:
        return (self.prompt_tokens * self.price_in + self.completion_tokens * self.price_out) / 1e6

    def summary(self) -> str:
        return (
            f"{self.calls} calls, {self.prompt_tokens} in / {self.completion_tokens} out tokens, "
            f"${self.cost_usd:.4f}"
        )


@dataclass
class Call:
    name: str
    system: str
    prompt: str
    reply: str


class MockLLM:
    """Deterministic LLM stand-in.

    ``name`` labels the model in traces (e.g. ``"small"`` vs ``"large"``) so that
    examples can show routing work to cheaper models. ``price`` is (in, out) USD per
    1M tokens and only affects the simulated cost report.
    """

    def __init__(self, responder: Responder, name: str = "mock", price: tuple[float, float] = (3.0, 15.0)):
        self.responder = responder
        self.name = name
        self.usage = Usage(price_in=price[0], price_out=price[1])
        self.calls: list[Call] = []
        self._lock = threading.Lock()  # examples call the mock from worker threads

    def complete(self, prompt: str, system: str = "") -> str:
        reply = self.responder(prompt, system)
        if not isinstance(reply, str):
            raise TypeError(f"responder returned {type(reply).__name__}, expected str")
        with self._lock:
            self.calls.append(Call(self.name, system, prompt, reply))
            self.usage.calls += 1
            self.usage.prompt_tokens += _tokens(system + " " + prompt)
            self.usage.completion_tokens += _tokens(reply)
        return reply


class NoRuleMatched(LookupError):
    pass


def rules(pairs: Iterable[tuple[Trigger, Reply]], default: Reply | None = None) -> Responder:
    """Build a responder from ordered ``(trigger, reply)`` pairs.

    * A ``str`` trigger matches when it appears (case-insensitively) in system+prompt.
    * A callable trigger is called with ``(prompt, system)`` and must return bool.
    * A ``str`` reply is returned as-is; a callable reply is called with ``(prompt, system)``.

    If nothing matches and no ``default`` is given, ``NoRuleMatched`` is raised —
    loud failure beats a silently wrong example.
    """
    compiled = list(pairs)

    def respond(prompt: str, system: str) -> str:
        haystack = f"{system}\n{prompt}".lower()
        for trigger, reply in compiled:
            hit = trigger.lower() in haystack if isinstance(trigger, str) else trigger(prompt, system)
            if hit:
                return reply(prompt, system) if callable(reply) else reply
        if default is None:
            raise NoRuleMatched(f"no mock rule matched prompt: {prompt[:80]!r}")
        return default(prompt, system) if callable(default) else default

    return respond


_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def extract_json(text: str):
    """Parse the first JSON object/array in ``text`` (models often wrap JSON in prose).

    Raises ``ValueError`` with a short message if none is found — callers treat that
    as a validation failure rather than crashing.
    """
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no JSON found in model output")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from None
