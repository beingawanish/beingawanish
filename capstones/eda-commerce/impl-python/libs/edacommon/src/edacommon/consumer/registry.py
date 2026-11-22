"""Handlers registered by ``ce_type`` (Avro full name) together with their reader schema."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from edacommon.db import UnitOfWork
from edacommon.envelope import MessageContext


class ContractRecord(Protocol):
    AVRO_NAME: str

    @classmethod
    def from_avro(cls, d: dict[str, Any]) -> Any: ...


T = TypeVar("T")
HandlerFn = Callable[[Any, MessageContext, UnitOfWork], None]


@dataclass(frozen=True, slots=True)
class Handler:
    record_type: str                      # ce_type and the reader schema name
    decode: Callable[[dict[str, Any]], Any]
    fn: HandlerFn

    @property
    def name(self) -> str:
        return getattr(self.fn, "__qualname__", repr(self.fn))


class HandlerRegistry:
    """Maps ``ce_type`` to a handler. Unknown types are *ignored* by the runtime, never failed."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, record_cls: type[Any], fn: HandlerFn, *, raw: bool = False) -> None:
        record_type: str = record_cls.AVRO_NAME
        if record_type in self._handlers:
            raise ValueError(f"handler for {record_type} already registered")
        decode: Callable[[dict[str, Any]], Any] = (lambda d: d) if raw else record_cls.from_avro
        self._handlers[record_type] = Handler(record_type, decode, fn)

    def handler(self, record_cls: type[Any], *, raw: bool = False) -> Callable[[HandlerFn], HandlerFn]:
        def deco(fn: HandlerFn) -> HandlerFn:
            self.register(record_cls, fn, raw=raw)
            return fn

        return deco

    def get(self, ce_type: str | None) -> Handler | None:
        return self._handlers.get(ce_type) if ce_type else None

    def types(self) -> list[str]:
        return sorted(self._handlers)
